"""Gate D12: XKRX 거래일 목록 생성·해시와 수집 장부 대조 (API 호출 없음).

    python -m krb.collect.calendar_d12 build     # exchange_calendars 필요 (pip install -e '.[calendar]')
    python -m krb.collect.calendar_d12 compare   # 저장된 목록만 쓴다. 라이브러리 불필요

거래일 판정은 XKRX 달력으로만 한다(AGENTS.md 1절). 종목기본정보 API는 휴장일에도 행을 주므로
데이터 쪽 거래일은 두 시장 일별매매정보가 모두 OK인 날로 본다.
2026-10-23 클라우드 실행: exchange_calendars 4.13.2, 1,332거래일,
SHA256 79720a5786313959cc0164c1ce2d6b390eca659f9832b57fe5f95a473b006817, N_warm 344.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path

from . import krx
from .core import Ledger, weekdays

START, END = dt.date(2017, 8, 1), dt.date(2022, 12, 29)
SESSIONS_NAME = "XKRX_sessions_20170801_20221229.txt"
EXPECTED_SHA256 = "79720a5786313959cc0164c1ce2d6b390eca659f9832b57fe5f95a473b006817"
TRADE = ("stk_bydd_trd", "ksq_bydd_trd")
MASTER = ("stk_isu_base_info", "ksq_isu_base_info")


def default_sessions_path(data_root: Path) -> Path:
    return data_root / "processed" / "xkrx" / SESSIONS_NAME


def load_sessions(path: Path) -> list[dt.date]:
    with path.open(encoding="utf-8") as f:
        return [dt.date.fromisoformat(line.strip()) for line in f if line.strip()]


def sessions_bytes(sessions: list[dt.date]) -> bytes:
    return "".join(f"{d.isoformat()}\n" for d in sessions).encode()


def build_sessions(start: dt.date = START, end: dt.date = END):
    """(거래일 목록, 평일 휴장일 → 사유) — exchange_calendars가 있어야 한다."""
    import exchange_calendars as xcals  # 선택 의존성

    cal = xcals.get_calendar("XKRX", start="2015-01-01", end="2023-12-31")
    sessions = [d.date() for d in cal.sessions_in_range(start.isoformat(), end.isoformat())]
    names = {}
    if cal.regular_holidays is not None:
        for ts, name in cal.regular_holidays.holidays(start.isoformat(), end.isoformat(), return_name=True).items():
            names[ts.date()] = str(name)
    s = set(sessions)
    closed = {d: names.get(d, "ADHOC") for d in weekdays(start, end) if d not in s}
    return sessions, closed, xcals.__version__


def compare(data_root: Path, sessions: list[dt.date], start: dt.date = START, end: dt.date = END) -> dict:
    """장부의 OK/EMPTY와 XKRX 거래일을 대조한다. 신호·수익률은 쓰지 않는다."""
    ledger = Ledger(krx.Layout(data_root).ledger)

    def st(api, d):
        r = ledger.get(krx.ledger_key(api, d))
        return r.get("status") if r else None

    sess = set(sessions)
    wk = list(weekdays(start, end))
    both_ok = {d for d in wk if all(st(a, d) == "OK" for a in TRADE)}
    both_empty = {d for d in wk if all(st(a, d) == "EMPTY" for a in TRADE)}
    closed = [d for d in wk if d not in sess]
    return {
        "range": [start.isoformat(), end.isoformat()],
        "weekdays": len(wk),
        "xkrx_sessions": len(sessions),
        "xkrx_sessions_sha256": hashlib.sha256(sessions_bytes(sessions)).hexdigest(),
        "weekend_sessions": [d.isoformat() for d in sessions if d.weekday() >= 5],
        "xkrx_closed_weekdays": len(closed),
        "empty_trade_days": len(both_empty),
        "both_trade_ok_days": len(both_ok),
        "mixed_days": sorted(d.isoformat() for d in set(wk) - both_ok - both_empty),
        "empty_and_xkrx_closed": len(both_empty & set(closed)),
        "empty_but_xkrx_session": sorted(d.isoformat() for d in both_empty & sess),
        "xkrx_closed_but_data_ok": sorted(d.isoformat() for d in set(closed) - both_empty),
        "data_days_eq_sessions": both_ok == sess,
        "per_market_missing_sessions": {a: sorted(d.isoformat() for d in sess if st(a, d) != "OK") for a in TRADE},
        "master_status_on_weekdays": dict(collections.Counter(st(a, d) for a in MASTER for d in wk)),
        "N_warm": len([d for d in sessions if d <= dt.date(2018, 12, 28)]),
        "sessions_by_year": dict(collections.Counter(d.year for d in sessions)),
    }


def main(argv=None) -> int:
    from .__main__ import find_repo_root
    p = argparse.ArgumentParser(prog="python -m krb.collect.calendar_d12")
    p.add_argument("cmd", choices=["build", "compare"])
    p.add_argument("--data-root", type=Path, default=None)
    a = p.parse_args(argv)
    root = a.data_root or find_repo_root(Path.cwd()) / "data"
    path = default_sessions_path(root)
    if a.cmd == "build":
        sessions, closed, ver = build_sessions()
        b = sessions_bytes(sessions)
        if path.exists() and path.read_bytes() != b:
            raise SystemExit(f"{path} 가 이미 있고 내용이 다르다. 덮어쓰지 않는다")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b)
        print(json.dumps({"library": f"exchange_calendars {ver}", "sessions": len(sessions),
                          "sha256": hashlib.sha256(b).hexdigest(), "closed_weekdays": len(closed)}))
    else:
        sessions = load_sessions(path)
        res = compare(root, sessions)
        res["sha256_matches_d12_record"] = res["xkrx_sessions_sha256"] == EXPECTED_SHA256
        print(json.dumps(res, ensure_ascii=False))
        ok = res["data_days_eq_sessions"] and res["sha256_matches_d12_record"] and not res["mixed_days"]
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
