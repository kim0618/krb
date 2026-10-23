"""월 단위 전달용 폴더 만들기: 그 달 원본·정규화·장부 기록·검증 결과 + SHA256SUMS (네트워크 없음).

    python -m krb.collect.export krx  --ym 202005 --out <dir>
    python -m krb.collect.export dart --ym 202005 --out <dir>

out/<name>/ 가 이미 있으면 덮어쓰지 않는다. 압축(tar.gz)은 호출자가 한다.
KRX 폴더: raw_krx/<api>/<YYYY>/*.json, processed_krx/<api>/<YYYY>/*.csv, raw_krx/_ledger_month.jsonl,
          verify.json, quality.json, README.txt, SHA256SUMS
DART 폴더: raw_opendart_i003/<YYYY>/*.json, raw_opendart_i003/_ledger_month.jsonl, processed/*_classified.csv
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

from . import krx, normalize
from .core import RESEARCH_CUTOFF, weekdays


def write_sha256sums(dest: Path) -> int:
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(dest).as_posix()}"
             for p in sorted(dest.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"]
    (dest / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def month_window(ym: str) -> tuple[dt.date, dt.date]:
    y, m = int(ym[:4]), int(ym[4:])
    end = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    return dt.date(y, m, 1), min(end, RESEARCH_CUTOFF)


def _fresh(out_root: Path, name: str) -> Path:
    dest = out_root / name
    if dest.exists():
        raise FileExistsError(f"{dest} 가 이미 있다. 덮어쓰지 않는다")
    return dest


def _summary(r: dict) -> dict:
    return {k: (len(v) if isinstance(v, list) else v) for k, v in r.items()}


def export_krx_month(data_root: Path, ym: str, out_root: Path) -> dict:
    dest = _fresh(out_root, f"kr6_krx_{ym}")
    copied = 0
    for api in krx.APIS:
        for sub, ext, tgt in (("raw/krx", "json", "raw_krx"), ("processed/krx", "csv", "processed_krx")):
            for p in sorted((data_root / sub / api / ym[:4]).glob(f"{ym}*.{ext}")):
                t = dest / tgt / api / ym[:4] / p.name
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, t)
                copied += 1
    (dest / "raw_krx").mkdir(parents=True, exist_ok=True)
    recs = []
    with krx.Layout(data_root).ledger.open(encoding="utf-8") as f:
        recs = [r for r in map(json.loads, f) if r["bas_dd"].startswith(ym)]
    with (dest / "raw_krx" / "_ledger_month.jsonl").open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    a, b = month_window(ym)
    layout = krx.Layout(data_root)
    (dest / "verify.json").write_text(json.dumps(_summary(krx.verify(layout, a, b)), ensure_ascii=False) + "\n",
                                      encoding="utf-8")
    (dest / "quality.json").write_text(json.dumps(normalize.quality(layout, weekdays(a, b)), ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    (dest / "README.txt").write_text(
        f"KR-6 KRX collection {a}..{b}\n"
        "Source: KRX OpenAPI (stk/ksq bydd_trd, stk/ksq isu_base_info). No key, cookie or HTTP headers included.\n"
        "KRX terms: non-commercial; third-party provision prohibited; use ends with the service contract (11-3).\n"
        "EMPTY trade days are holiday candidates only (XKRX check, Gate D12). Zero-volume rows are not classified as halts.\n",
        encoding="utf-8")
    return {"name": dest.name, "ledger_records": len(recs), "files_copied": copied, "hashed": write_sha256sums(dest)}


def export_dart_month(data_root: Path, ym: str, out_root: Path) -> dict:
    dest = _fresh(out_root, f"kr6_dart_i003_{ym}")
    pages = sorted((data_root / "raw" / "opendart_i003" / ym[:4]).glob(f"{ym}01_*_ALL_p*.json"))
    for p in pages:
        t = dest / "raw_opendart_i003" / ym[:4] / p.name
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, t)
    (dest / "raw_opendart_i003").mkdir(parents=True, exist_ok=True)
    with (data_root / "raw" / "opendart_i003" / "_ledger.jsonl").open(encoding="utf-8") as f:
        recs = [r for r in map(json.loads, f) if r["key"].startswith(f"{ym}01_")]
    with (dest / "raw_opendart_i003" / "_ledger_month.jsonl").open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    c = data_root / "processed" / "opendart_i003" / ym[:4] / f"{ym}_classified.csv"
    (dest / "processed").mkdir(parents=True, exist_ok=True)
    shutil.copy2(c, dest / "processed" / c.name)
    (dest / "README.txt").write_text(
        f"KR-6 OpenDART list.json pblntf_detail_ty=I003 (거래소 시장조치), month {ym}, corp_cls ALL, page_count 100.\n"
        "raw_opendart_i003/: API response bodies as received (no key, no URL, no headers). _ledger_month.jsonl: request params + status + sha256.\n"
        "processed/*_classified.csv: title-based candidate category only. effective_date is empty on purpose; PENDING_BODY = needs disclosure body.\n"
        "rcept_dt is the filing date, not the effective date. link_status/isin: stock_code matched to KRX master of the same or previous XKRX session.\n",
        encoding="utf-8")
    return {"name": dest.name, "pages": len(pages), "ledger_records": len(recs), "hashed": write_sha256sums(dest)}


def main(argv=None) -> int:
    from .__main__ import find_repo_root
    p = argparse.ArgumentParser(prog="python -m krb.collect.export")
    p.add_argument("kind", choices=["krx", "dart"])
    p.add_argument("--data-root", type=Path, default=None)
    p.add_argument("--ym", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    root = a.data_root or find_repo_root(Path.cwd()) / "data"
    fn = export_krx_month if a.kind == "krx" else export_dart_month
    print(json.dumps(fn(root, a.ym, a.out), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
