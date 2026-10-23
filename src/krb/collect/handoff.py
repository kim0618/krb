"""클라우드 → 로컬 데이터 이전: 아카이브 안전 검사·복원·매니페스트 검증 (네트워크 없음).

    python -m krb.collect.handoff check-manifest --bundle <dir>          # 전달 파일 크기·SHA256
    python -m krb.collect.handoff restore --bundle <dir> [--apply]        # 기본은 dry-run

복원 규칙
- tar 멤버는 일반 파일·디렉터리만 허용한다. 절대경로, '..', 심볼릭·하드 링크, 장치 파일이 있으면 그 아카이브를 거부한다.
- 먼저 임시 폴더(staging)에 풀고 내부 SHA256SUMS를 모두 검증한 뒤에만 data/로 옮긴다.
- 대상 파일이 이미 있으면 SHA256이 같을 때만 건너뛰고, 다르면 CONFLICT로 보고하고 덮어쓰지 않는다.
- 대상 경로가 data/ 밖으로 나가거나 중간 경로에 심볼릭 링크가 있으면 거부한다.
아카이브 종류: kr6_krx_YYYYMM / kr6_r1_krx_201901 (KRX 월별), kr6_dart_i003_YYYYMM (I003 월별),
kr6_handoff_aux_* (data/ 아래 상대 경로를 그대로 담은 보조 묶음).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def sha256_path(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class UnsafeArchive(Exception):
    pass


def check_members(tf: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = tf.getmembers()
    for m in members:
        p = PurePosixPath(m.name)
        if p.is_absolute() or ".." in p.parts or m.name.startswith("/") or "\\" in m.name:
            raise UnsafeArchive(f"경로 이탈 멤버: {m.name}")
        if not (m.isfile() or m.isdir()):
            raise UnsafeArchive(f"일반 파일·디렉터리가 아닌 멤버(링크 등): {m.name}")
    return members


def safe_extract(tar_path: Path, staging: Path) -> Path:
    """검사를 통과한 아카이브만 staging에 푼다. 최상위 폴더 하나를 돌려준다."""
    with tarfile.open(tar_path, "r:gz") as tf:
        members = check_members(tf)
        tops = {PurePosixPath(m.name).parts[0] for m in members}
        if len(tops) != 1:
            raise UnsafeArchive(f"최상위 폴더가 하나가 아니다: {sorted(tops)[:5]}")
        tf.extractall(staging, members=members, filter="data")
    return staging / tops.pop()


def verify_sha256sums(folder: Path) -> list[str]:
    """SHA256SUMS의 모든 줄을 검사한다. 실패 목록(없으면 빈 목록)."""
    bad = []
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sha, rel = line.split("  ", 1)
        p = folder / rel
        if not p.is_file() or p.is_symlink() or sha256_path(p) != sha:
            bad.append(rel)
    return bad


def plan_archive(folder: Path) -> list[tuple[Path, str]]:
    """(staging 안 파일, data/ 기준 상대 경로) 목록."""
    name, out = folder.name, []
    if re.fullmatch(r"kr6_(r1_)?krx_\d{6}", name):
        for p in sorted(folder.rglob("*")):
            rel = p.relative_to(folder).parts
            if not p.is_file() or len(rel) != 4:
                continue  # 월별 장부·verify·quality·README·SHA256SUMS는 복원 대상이 아니다(전체 장부는 보조 묶음)
            top, api, yyyy, fn = rel
            sub = {"raw_krx": "raw/krx", "processed_krx": "processed/krx"}.get(top)
            if sub:
                out.append((p, f"{sub}/{api}/{yyyy}/{fn}"))
    elif re.fullmatch(r"kr6_dart_i003_\d{6}", name):
        for p in sorted(folder.rglob("*")):
            rel = p.relative_to(folder).parts
            if p.is_file() and rel[0] == "raw_opendart_i003" and len(rel) == 3:
                out.append((p, f"raw/opendart_i003/{rel[1]}/{rel[2]}"))
            elif p.is_file() and rel[0] == "processed" and len(rel) == 2:
                out.append((p, f"processed/opendart_i003/{rel[1][:4]}/{rel[1]}"))
    elif name.startswith("kr6_handoff_aux"):
        for p in sorted((folder / "data").rglob("*")):
            if p.is_file():
                out.append((p, p.relative_to(folder / "data").as_posix()))
    else:
        raise UnsafeArchive(f"알 수 없는 아카이브 종류: {name}")
    return out


def _inside(data_root: Path, rel: str) -> Path:
    dst = data_root / rel
    cur = data_root
    for part in PurePosixPath(rel).parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            raise UnsafeArchive(f"대상 경로에 심볼릭 링크: {cur}")
    if dst.is_symlink():
        raise UnsafeArchive(f"대상 파일이 심볼릭 링크: {dst}")
    root = data_root.resolve()
    if root not in dst.resolve().parents:
        raise UnsafeArchive(f"data/ 밖으로 나가는 경로: {rel}")
    return dst


def install(plan: list[tuple[Path, str]], data_root: Path, apply: bool) -> dict:
    st = {"new": 0, "identical": 0, "conflict": []}
    for src, rel in plan:
        dst = _inside(data_root, rel)
        if dst.exists():
            if sha256_path(dst) == sha256_path(src):
                st["identical"] += 1
            else:
                st["conflict"].append(rel)
            continue
        st["new"] += 1
        if apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".part")
            shutil.copyfile(src, tmp)
            tmp.replace(dst)
    return st


def restore(bundle: Path, data_root: Path, apply: bool = False) -> dict:
    """bundle의 *.tar.gz를 모두 검사하고(첫 오류에서 해당 아카이브 거부) 복원한다."""
    report = {"apply": apply, "archives": {}, "rejected": {}, "conflict": []}
    with tempfile.TemporaryDirectory(prefix="krb_restore_") as tmp:
        for i, tgz in enumerate(sorted(bundle.glob("*.tar.gz"))):
            try:
                folder = safe_extract(tgz, Path(tmp) / str(i))
                bad = verify_sha256sums(folder)
                if bad:
                    raise UnsafeArchive(f"내부 SHA256 불일치 {len(bad)}건: {bad[:3]}")
                st = install(plan_archive(folder), data_root, apply)
            except (UnsafeArchive, tarfile.TarError, OSError, ValueError) as e:
                report["rejected"][tgz.name] = str(e)
                continue
            finally:
                shutil.rmtree(Path(tmp) / str(i), ignore_errors=True)
            report["archives"][tgz.name] = {"new": st["new"], "identical": st["identical"],
                                            "conflict": len(st["conflict"])}
            report["conflict"] += [f"{tgz.name}:{c}" for c in st["conflict"]]
    return report


def check_manifest(bundle: Path, manifest: Path) -> dict:
    """전달 매니페스트(TSV: relpath, size, sha256, ...)의 파일을 bundle에서 확인한다."""
    res = {"ok": 0, "missing": [], "bad": []}
    with manifest.open(encoding="utf-8") as f:
        for r in csv.DictReader((line for line in f if not line.startswith("#")), delimiter="\t"):
            p = bundle / r["relpath"]
            if not p.is_file():
                res["missing"].append(r["relpath"])
            elif p.stat().st_size != int(r["size"]) or sha256_path(p) != r["sha256"]:
                res["bad"].append(r["relpath"])
            else:
                res["ok"] += 1
    return res


def main(argv=None) -> int:
    from .__main__ import find_repo_root
    p = argparse.ArgumentParser(prog="python -m krb.collect.handoff")
    p.add_argument("cmd", choices=["check-manifest", "restore"])
    p.add_argument("--bundle", type=Path, required=True, help="전달받은 파일을 모은 폴더")
    p.add_argument("--manifest", type=Path, default=None, help="기본: <bundle>/KR6_HANDOFF_MANIFEST.tsv")
    p.add_argument("--data-root", type=Path, default=None)
    p.add_argument("--apply", action="store_true", help="없으면 dry-run(아무것도 쓰지 않음)")
    a = p.parse_args(argv)
    if a.cmd == "check-manifest":
        res = check_manifest(a.bundle, a.manifest or a.bundle / "KR6_HANDOFF_MANIFEST.tsv")
        print(json.dumps(res, ensure_ascii=False))
        return 0 if not res["missing"] and not res["bad"] else 2
    root = a.data_root or find_repo_root(Path.cwd()) / "data"
    res = restore(a.bundle, root, a.apply)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if not res["rejected"] and not res["conflict"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
