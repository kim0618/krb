"""KIND 상장폐지현황(사용자 수동 다운로드) 파싱·KRX 연결·완전성 점검 (네트워크 없음).

    python -m krb.collect.kind --kospi <KOSPI.xls> --kosdaq <KOSDAQ.xls> --out linked.csv

KIND의 "EXCEL" 파일은 확장자만 .xls인 EUC-KR HTML 표다(열: 번호·회사명·종목코드·폐지일자·폐지사유·비고).
- 이 목록은 상장폐지 뒤 작성된 정보라 완전성 점검 전용이다. 당시 투자 판단에 소급하지 않는다.
- 회사명은 현재 이름이다. 연결은 종목코드와 날짜로만 한다.
- 사유 "유가증권시장 상장"은 퇴장이 아니라 시장 이전(MARKET_TRANSFER)이다.
- 2026-10-23 반입: KOSPI 34건, KOSDAQ 152건, 186건 모두 폐지일 직전 거래일에 해당 시장 마스터 마지막 등장.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import re
from pathlib import Path

from .calendar_d12 import default_sessions_path, load_sessions

MASTER_API = {"KOSPI": "stk_isu_base_info", "KOSDAQ": "ksq_isu_base_info"}
HEADER = ["번호", "회사명", "종목코드", "폐지일자", "폐지사유", "비고"]
USE_NOTE = "completeness_check_only (사후 작성 정보, 당시 의사결정에 소급 금지)"


def parse_kind_html(raw: bytes) -> list[list[str]]:
    """표의 행을 셀 문자열 목록으로. 첫 행은 머리글."""
    t = raw.decode("cp949")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, flags=re.S | re.I):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.S | re.I)]
        if cells:
            rows.append(cells)
    if not rows or rows[0] != HEADER:
        raise ValueError(f"KIND 상장폐지현황 머리글이 아니다: {rows[:1]}")
    return rows


def master_presence(data_root: Path, sessions: list[dt.date]) -> dict:
    """(종목코드, 시장) → 첫·마지막 등장일과 당시 필드. 전 기간 종목기본정보를 한 번 훑는다."""
    seen = {}
    for d in sessions:
        for mk, api in MASTER_API.items():
            p = data_root / "raw" / "krx" / api / f"{d:%Y}" / f"{d:%Y%m%d}.json"
            with p.open(encoding="utf-8") as f:
                for r in json.load(f)["OutBlock_1"]:
                    k = (r["ISU_SRT_CD"], mk)
                    s = seen.get(k)
                    if s is None:
                        seen[k] = s = {"first": d, "isin": r["ISU_CD"], "kind": r.get("KIND_STKCERT_TP_NM"),
                                       "secu": r.get("SECUGRP_NM")}
                    s["last"], s["name_last"] = d, r["ISU_ABBRV"]
    return seen


def link(rows_by_market: dict[str, list[list[str]]], seen: dict, sessions: list[dt.date]) -> list[dict]:
    prev = {d: sessions[i - 1] if i else None for i, d in enumerate(sessions)}
    out = []
    for mk, rows in rows_by_market.items():
        for r in rows:
            v = seen.get((r[2], mk))
            dd = dt.date.fromisoformat(r[3])
            exp = prev.get(dd) or max((s for s in sessions if s < dd), default=None)
            lk = "NOT_FOUND" if v is None else ("LAST_SEEN=PREV_SESSION" if v["last"] == exp else "LAST_SEEN_MISMATCH")
            v = v or {}
            out.append({"market": mk, "kind_no": r[0], "kind_name": r[1], "stock_code": r[2], "delist_date": r[3],
                        "reason": r[4], "note": r[5],
                        "type": "MARKET_TRANSFER" if r[4] == "유가증권시장 상장" else "EXIT",
                        "isin_krx": v.get("isin", ""), "krx_name_last": v.get("name_last", ""),
                        "krx_first_seen": str(v.get("first", "")), "krx_last_seen": str(v.get("last", "")),
                        "krx_secugrp": v.get("secu", ""), "krx_kind": v.get("kind", ""), "link": lk,
                        "delist_trading_period": "NOT_IN_KIND_LIST", "use": USE_NOTE})
    return out


def unexplained_exits(seen: dict, linked: list[dict], last_session: dt.date) -> dict:
    """마스터에서 사라졌는데 KIND 목록에 없는 (코드, 시장). 시장 이전·보통주 외는 따로 센다."""
    kind = {(r["stock_code"], r["market"]) for r in linked}
    out = {"in_kind": 0, "moved": [], "non_common": [], "unexplained_common": []}
    for (code, mk), v in seen.items():
        if v["last"] >= last_session:
            continue
        if (code, mk) in kind:
            out["in_kind"] += 1
            continue
        other = seen.get((code, "KOSDAQ" if mk == "KOSPI" else "KOSPI"))
        item = (code, mk, v["name_last"], v["last"].isoformat(), v["kind"])
        if other and other["first"] > v["last"]:
            out["moved"].append(item)
        elif v["kind"] and v["kind"] != "보통주":
            out["non_common"].append(item)
        else:
            out["unexplained_common"].append(item)
    return out


def main(argv=None) -> int:
    from .__main__ import find_repo_root
    p = argparse.ArgumentParser(prog="python -m krb.collect.kind")
    p.add_argument("--data-root", type=Path, default=None)
    p.add_argument("--sessions", type=Path, default=None)
    p.add_argument("--kospi", type=Path, required=True)
    p.add_argument("--kosdaq", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    root = a.data_root or find_repo_root(Path.cwd()) / "data"
    sessions = load_sessions(a.sessions or default_sessions_path(root))
    rows = {"KOSPI": parse_kind_html(a.kospi.read_bytes())[1:], "KOSDAQ": parse_kind_html(a.kosdaq.read_bytes())[1:]}
    seen = master_presence(root, sessions)
    linked = link(rows, seen, sessions)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linked[0]))
        w.writeheader()
        w.writerows(linked)
    gap = unexplained_exits(seen, linked, sessions[-1])
    print(json.dumps({"rows": len(linked), "link": {k: sum(r["link"] == k for r in linked) for k in
                      ("LAST_SEEN=PREV_SESSION", "LAST_SEEN_MISMATCH", "NOT_FOUND")},
                      "in_kind": gap["in_kind"], "moved": len(gap["moved"]), "non_common": len(gap["non_common"]),
                      "unexplained_common": gap["unexplained_common"]}, ensure_ascii=False))
    return 0 if not gap["unexplained_common"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
