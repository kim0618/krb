"""KR-6 로컬 수집기 CLI.

    python -m krb.collect plan    --start 2017-08-01 --end 2022-12-29
    python -m krb.collect krx     --start 2019-01-01 --end 2019-01-31
    python -m krb.collect verify  --start 2019-01-01 --end 2019-01-31
    python -m krb.collect normalize --start 2019-01-01 --end 2019-01-31
    python -m krb.collect quality --start 2019-01-01 --end 2019-01-31
    python -m krb.collect dart-i003   --start 2019-01-01 --end 2019-01-31
    python -m krb.collect fsc-rights  --start 2019-01-01 --end 2019-01-31
    python -m krb.collect dart-corpcode

data 경로는 저장소 루트(pyproject.toml의 name = "krb")의 `data/`가 기본이다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import aux_sources, krx, normalize
from .core import (
    RESEARCH_CUTOFF,
    CutoffViolation,
    Fetcher,
    MissingCredential,
    RetryPolicy,
    check_window,
    urllib_transport,
    weekdays,
)


def find_repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        f = p / "pyproject.toml"
        if f.exists() and 'name = "krb"' in f.read_text(encoding="utf-8"):
            return p
    raise SystemExit("KR-B 저장소 루트(pyproject.toml, name = \"krb\")를 찾지 못했다. 저장소 안에서 실행한다")


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m krb.collect")
    p.add_argument("--data-root", type=Path, default=None, help="기본: 저장소 루트의 data/")
    sub = p.add_subparsers(dest="cmd", required=True)

    def window(sp, need=True):
        sp.add_argument("--start", type=_date, required=need)
        sp.add_argument("--end", type=_date, required=need)

    def net(sp, default_max):
        sp.add_argument("--max-calls", type=int, default=default_max, help="이번 실행의 호출 상한")
        sp.add_argument("--min-interval", type=float, default=0.5, help="호출 간 최소 간격(초)")
        sp.add_argument("--max-attempts", type=int, default=3)

    for name in ("plan", "verify", "normalize", "quality"):
        sp = sub.add_parser(name)
        window(sp)
        sp.add_argument("--apis", nargs="+", default=list(krx.APIS))
    sp = sub.add_parser("krx")
    window(sp)
    sp.add_argument("--apis", nargs="+", default=list(krx.APIS))
    sp.add_argument("--network-secret", action="store_true",
                    help="AUTH_KEY를 환경변수가 아니라 실행 환경의 프록시가 넣는 경우")
    net(sp, 9000)
    for name in ("dart-i003", "fsc-rights"):
        sp = sub.add_parser(name)
        window(sp)
        net(sp, 2000)
        if name == "dart-i003":
            sp.add_argument("--corp-cls", default="", choices=["", "Y", "K"])
    sp = sub.add_parser("dart-corpcode")
    net(sp, 1)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.data_root or (find_repo_root(Path.cwd()) / "data")
    layout = krx.Layout(root)
    if getattr(args, "start", None):
        check_window(args.start, args.end)  # 2022-12-29 뒤, 2017-08-01 앞은 여기서 거부한다

    def fetcher():
        return Fetcher(urllib_transport, RetryPolicy(max_attempts=args.max_attempts, min_interval=args.min_interval),
                       max_calls=args.max_calls)

    if args.cmd == "plan":
        jobs = krx.plan(args.start, args.end, args.apis)
        days = len({d for _, d in jobs})
        print(json.dumps({"weekdays": days, "requests": len(jobs), "cutoff": RESEARCH_CUTOFF.isoformat()}))
    elif args.cmd == "krx":
        print(json.dumps(krx.collect(layout, args.start, args.end, fetcher(), args.apis, args.network_secret),
                         ensure_ascii=False))
    elif args.cmd == "verify":
        r = krx.verify(layout, args.start, args.end, args.apis)
        summary = {k: (len(v) if isinstance(v, list) else v) for k, v in r.items()}
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if not (r["hash_mismatch"] or r["file_missing"] or r["part_files"]) else 2
    elif args.cmd == "normalize":
        print(json.dumps(normalize.normalize(layout, weekdays(args.start, args.end), args.apis)))
    elif args.cmd == "quality":
        print(json.dumps(normalize.quality(layout, weekdays(args.start, args.end)), ensure_ascii=False))
    elif args.cmd == "dart-i003":
        print(json.dumps(aux_sources.collect_dart_i003(root, args.start, args.end, fetcher(), args.corp_cls),
                         ensure_ascii=False))
    elif args.cmd == "fsc-rights":
        print(json.dumps(aux_sources.collect_fsc_rights(root, args.start, args.end, fetcher()), ensure_ascii=False))
    elif args.cmd == "dart-corpcode":
        print(json.dumps(aux_sources.collect_dart_corpcode(root, fetcher())))
    return 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (MissingCredential, CutoffViolation) as e:
        print(f"중단: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(run())
