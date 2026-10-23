"""KR-6 수집분 전체 점검 (네트워크 없음).

    python -m krb.collect.audit months [--archives <dir>]   # 65개월 완료·무결성·압축파일 SHA256
    python -m krb.collect.audit d6a                         # OHLC 이상 행 목록과 Q5 거래대금 범위 점검

D6(a)의 판정 근거가 아니라 정황 증거다. 원본·정규화 파일은 읽기만 한다.
2026-10-23 클라우드 결과: 65/65개월 완료, 요청 5,652(OK 5,490·EMPTY 162), 시세 3,101,756행,
고유 ISIN 2,749, OHLC 이상 9행, Q5 위반 4,446/3,005,145(0.148%).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path

from . import krx, normalize
from .calendar_d12 import END, START, default_sessions_path, load_sessions
from .core import Ledger, weekdays
from .dart_i003 import months
from .export import month_window

PRICE = ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC")


def _num(v):
    s = str(v).replace(",", "").strip()
    return None if s in ("", "-") else float(s)


def archive_name(ym: str) -> str:
    return "kr6_r1_krx_201901" if ym == "201901" else f"kr6_krx_{ym}"


def audit_months(data_root: Path, archives: Path | None = None) -> dict:
    layout = krx.Layout(data_root)
    rows, missing, total = [], [], collections.Counter()
    for ym in months(f"{START:%Y%m}", f"{END:%Y%m}"):
        a, b = month_window(ym)
        v = krx.verify(layout, a, b)
        bad = v["failed_or_missing"] + v["file_missing"] + v["hash_mismatch"]
        missing += bad
        csv_n = sum(1 for api in krx.APIS for _ in (data_root / "processed/krx" / api / ym[:4]).glob(f"{ym}*.csv"))
        tgz = archives / f"{archive_name(ym)}.tar.gz" if archives else None
        sha = hashlib.sha256(tgz.read_bytes()).hexdigest() if tgz and tgz.exists() else None
        exp = len(list(weekdays(a, b))) * len(krx.APIS)
        rows.append({"ym": ym, "expected": exp, "complete": v["complete"], "ok": v["ok"], "empty": v["empty"],
                     "bad": len(bad), "csv": csv_n, "csv_expected": v["ok"],
                     "trade_rows": v["rows_by_api"].get("stk_bydd_trd", 0) + v["rows_by_api"].get("ksq_bydd_trd", 0),
                     "archive": tgz.name if sha else None, "size": tgz.stat().st_size if sha else None, "sha256": sha})
        for k in ("expected", "complete", "ok", "empty", "trade_rows"):
            total[k] += rows[-1][k]
    return {"months": len(rows), "months_complete": sum(r["bad"] == 0 and r["complete"] == r["expected"] for r in rows),
            "months_csv_ok": sum(r["csv"] == r["csv_expected"] for r in rows),
            "months_with_archive": sum(bool(r["sha256"]) for r in rows), "totals": dict(total),
            "missing_keys": missing, "rows": rows}


def d6a_evidence(data_root: Path, sessions: list[dt.date]) -> dict:
    layout, ledger = krx.Layout(data_root), Ledger(krx.Layout(data_root).ledger)
    anoms, tot, below, above = [], 0, 0, 0
    by_year = collections.Counter()
    for api in ("stk_bydd_trd", "ksq_bydd_trd"):
        for d in sessions:
            rec = ledger.get(krx.ledger_key(api, d))
            if not rec or rec["status"] != "OK":
                continue
            for r in normalize._rows(layout, api, d):
                o, h, lo, c, v, val = (_num(r.get(k)) for k in PRICE + ("ACC_TRDVOL", "ACC_TRDVAL"))
                if not v or v <= 0:
                    continue
                if None in (o, h, lo, c) or not (0 < lo <= min(o, c) and max(o, c) <= h):
                    anoms.append([d.isoformat(), api[:3], r.get("ISU_CD"), r.get("ISU_NM")] + [r.get(k) for k in PRICE]
                                 + [r.get("ACC_TRDVOL"), r.get("ACC_TRDVAL")])
                    continue
                tot += 1
                if val < lo * v * 0.995:
                    below += 1
                    by_year[d.year] += 1
                elif val > h * v * 1.005:
                    above += 1
                    by_year[d.year] += 1
    return {"ohlc_anomalies": anoms, "q5_traded_rows": tot, "q5_violations": below + above, "below": below,
            "above": above, "rate_pct": round(100 * (below + above) / tot, 4) if tot else None,
            "by_year": dict(by_year)}


def main(argv=None) -> int:
    from .__main__ import find_repo_root
    p = argparse.ArgumentParser(prog="python -m krb.collect.audit")
    p.add_argument("cmd", choices=["months", "d6a"])
    p.add_argument("--data-root", type=Path, default=None)
    p.add_argument("--archives", type=Path, default=None, help="kr6_krx_YYYYMM.tar.gz 폴더(있으면 SHA256 기록)")
    a = p.parse_args(argv)
    root = a.data_root or find_repo_root(Path.cwd()) / "data"
    if a.cmd == "months":
        res = audit_months(root, a.archives)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res["months_complete"] == res["months"] and not res["missing_keys"] else 2
    print(json.dumps(d6a_evidence(root, load_sessions(default_sessions_path(root))), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
