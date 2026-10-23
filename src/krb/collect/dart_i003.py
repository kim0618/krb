"""OpenDART I003(거래소 시장조치) 목록 분류와 당시 KRX 종목 연결 (API 호출 없음).

    python -m krb.collect.dart_i003 --start 201708 --end 202212

출력: data/processed/opendart_i003/<YYYY>/<YYYYMM>_classified.csv. 원본 페이지는 읽기만 한다.
- 분류는 제목만 본 후보다. 효력일은 비워 두고 본문이 필요한 건은 PENDING_BODY로 둔다.
- `corp_cls`는 OpenDART의 *현재* 법인구분이다(상폐 회사는 E). 당시 시장은 접수일(휴장이면 직전 거래일)의
  KRX 종목기본정보에서 `stock_code`를 찾아서만 정한다. corp_cls로 거르면 상폐 회사 공시가 빠진다.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import datetime as dt
import json
import re
from pathlib import Path

from .calendar_d12 import default_sessions_path, load_sessions

RULES = [  # 순서대로 첫 일치. 제목 공백 제거 뒤 비교
    ("HALT_PERIOD_CHANGE", re.compile(r"정지기간변경")),
    ("HALT_RELEASE", re.compile(r"정지해제|거래재개")),
    ("HALT", re.compile(r"매매거래정지|거래정지")),
    ("DELIST_TRADING", re.compile(r"정리매매")),
    ("DELIST", re.compile(r"상장폐지")),
    ("OTHER_MARKET_NOTICE", re.compile(r"기타시장안내")),
    ("EX_RIGHTS_DIVIDEND", re.compile(r"권리락|배당락|권배락")),
]
NEEDS_BODY = {"HALT_PERIOD_CHANGE", "HALT_RELEASE", "HALT", "DELIST_TRADING", "DELIST",
              "OTHER_MARKET_NOTICE", "EX_RIGHTS_DIVIDEND"}
MASTERS = (("KOSPI", "stk_isu_base_info"), ("KOSDAQ", "ksq_isu_base_info"))


def classify(title: str) -> str:
    t = re.sub(r"\s+", "", title or "")
    t = re.sub(r"^\[[^\]]*\]", "", t)  # [기재정정] 등 접두어
    for name, rx in RULES:
        if rx.search(t):
            return name
    return "OTHER"


class Masters:
    def __init__(self, data_root: Path, sessions: list[dt.date]):
        self.root, self.sess, self._c = data_root / "raw" / "krx", sessions, {}

    def get(self, api, d):
        if (api, d) not in self._c:
            p = self.root / api / f"{d:%Y}" / f"{d:%Y%m%d}.json"
            if p.exists():
                with p.open(encoding="utf-8") as f:
                    self._c[(api, d)] = {r["ISU_SRT_CD"]: r for r in json.load(f).get("OutBlock_1", [])}
            else:
                self._c[(api, d)] = None
        return self._c[(api, d)]

    def asof(self, d):
        i = bisect.bisect_right(self.sess, d) - 1
        return self.sess[i] if i >= 0 else None

    def link(self, code: str, rd: dt.date) -> tuple[str, str, str, dt.date | None]:
        """(link_status, market_then, isin, master_session)"""
        s = self.asof(rd)
        if not code:
            return "NO_STOCK_CODE", "", "", s
        if s is None:
            return "NO_MASTER_FILE", "", "", s
        hits = [(mk, m[code]["ISU_CD"]) for mk, api in MASTERS if (m := self.get(api, s)) is not None and code in m]
        if len(hits) == 1:
            return ("LINKED_SAME_DAY" if s == rd else "LINKED_PREV_SESSION"), hits[0][0], hits[0][1], s
        return ("MULTI_MATCH" if hits else "NOT_IN_KOSPI_KOSDAQ_MASTER"), "", "", s


def classify_month(data_root: Path, ym: str, masters: Masters, out_root: Path | None = None) -> dict:
    pages = sorted((data_root / "raw" / "opendart_i003" / ym[:4]).glob(f"{ym}01_*_ALL_p*.json"))
    rows = []
    for p in pages:
        with p.open(encoding="utf-8") as f:
            rows += json.load(f).get("list", [])
    out, cnt, link, cls = [], collections.Counter(), collections.Counter(), collections.Counter()
    for r in rows:
        c = classify(r.get("report_nm", ""))
        rd = dt.datetime.strptime(r["rcept_dt"], "%Y%m%d").date()
        code, cc = (r.get("stock_code") or "").strip(), r.get("corp_cls")
        lst, mkt, isin, s = masters.link(code, rd)
        cnt[c] += 1
        link[lst] += 1
        cls[cc] += 1
        out.append({
            "rcept_no": r.get("rcept_no"), "rcept_dt": r.get("rcept_dt"), "corp_cls_current": cc,
            "corp_code": r.get("corp_code"), "corp_name": r.get("corp_name"), "stock_code": code,
            "report_nm": r.get("report_nm"), "flr_nm": r.get("flr_nm"), "rm": r.get("rm"),
            "category": c, "body_status": "PENDING_BODY" if c in NEEDS_BODY else "NOT_REQUIRED",
            "effective_date": "", "master_session": s.isoformat() if s else "",
            "link_status": lst, "market_then": mkt, "isin": isin, "available_at_basis": "rcept_dt (접수일, 시각 미상)",
        })
    dest = (out_root or data_root / "processed" / "opendart_i003") / ym[:4] / f"{ym}_classified.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else ["rcept_no"])
        w.writeheader()
        w.writerows(out)
    return {"pages": len(pages), "rows": len(rows), "dup_rcept_no": len(rows) - len({r.get("rcept_no") for r in rows}),
            "by_category": dict(cnt), "pending_body": sum(1 for x in out if x["body_status"] == "PENDING_BODY"),
            "link": dict(link), "corp_cls": dict(cls)}


def months(start: str, end: str) -> list[str]:
    y, m = int(start[:4]), int(start[4:])
    out = []
    while (y, m) <= (int(end[:4]), int(end[4:])):
        out.append(f"{y:04d}{m:02d}")
        y, m = y + (m == 12), m % 12 + 1
    return out


def main(argv=None) -> int:
    from .__main__ import find_repo_root
    p = argparse.ArgumentParser(prog="python -m krb.collect.dart_i003")
    p.add_argument("--data-root", type=Path, default=None)
    p.add_argument("--sessions", type=Path, default=None)
    p.add_argument("--start", default="201708")
    p.add_argument("--end", default="202212")
    p.add_argument("--out-root", type=Path, default=None, help="기본: data/processed/opendart_i003")
    a = p.parse_args(argv)
    root = a.data_root or find_repo_root(Path.cwd()) / "data"
    ms = Masters(root, load_sessions(a.sessions or default_sessions_path(root)))
    print(json.dumps({ym: classify_month(root, ym, ms, a.out_root) for ym in months(a.start, a.end)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
