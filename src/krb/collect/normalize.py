"""KRX 원본 → 정규화 CSV, 그리고 원시 데이터만 쓰는 기초 품질 집계.

정규화는 원본 필드를 이름·값 그대로 두고 메타 열만 붙인다. 보정·보간·형 변환을 하지 않는다.
여기서 하는 품질 집계는 데이터 계약 Q1~Q14 전체가 아니다(달력 대조, 상폐 대조, 기업행위 분류 없음).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from typing import Iterable

from .core import Ledger, atomic_write, sha256_file
from .krx import APIS, COMPLETE, Layout, ledger_key

META_COLS = ["krb_source", "krb_api", "krb_market", "krb_bas_dd", "krb_retrieved_at", "krb_raw_sha256"]


def _rows(layout: Layout, api: str, day: dt.date) -> list[dict]:
    with layout.raw_file(api, day).open(encoding="utf-8") as f:
        return json.load(f).get("OutBlock_1", [])


def normalize(layout: Layout, days: Iterable[dt.date], apis: Iterable[str] = tuple(APIS)) -> dict:
    ledger = Ledger(layout.ledger)
    out = {"written": 0, "skipped_not_complete": 0, "skipped_empty": 0}
    for day in days:
        for api in apis:
            rec = ledger.get(ledger_key(api, day))
            path = layout.raw_file(api, day)
            if not rec or rec.get("status") not in COMPLETE or not path.exists() \
                    or sha256_file(path) != rec.get("sha256"):
                out["skipped_not_complete"] += 1
                continue
            if rec["status"] == "EMPTY":
                out["skipped_empty"] += 1
                continue
            rows = _rows(layout, api, day)
            fields: list[str] = []
            for r in rows:
                for k in r:
                    if k not in fields:
                        fields.append(k)
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=fields + META_COLS, extrasaction="raise")
            w.writeheader()
            meta = {"krb_source": rec.get("source"), "krb_api": api, "krb_market": APIS[api]["market"],
                    "krb_bas_dd": rec["bas_dd"], "krb_retrieved_at": rec.get("retrieved_at"),
                    "krb_raw_sha256": rec.get("sha256")}
            for r in rows:
                w.writerow({**r, **meta})
            atomic_write(layout.processed_file(api, day), buf.getvalue().encode("utf-8"))
            out["written"] += 1
    return out


REQUIRED_TRADE = ["ISU_CD", "ISU_NM", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC",
                  "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP", "LIST_SHRS"]
REQUIRED_MASTER = ["ISU_CD", "ISU_SRT_CD", "ISU_NM", "LIST_DD", "MKT_TP_NM", "SECUGRP_NM",
                   "KIND_STKCERT_TP_NM", "LIST_SHRS"]


def _empty(v) -> bool:
    return v is None or str(v).strip() in ("", "-")


def quality(layout: Layout, days: Iterable[dt.date]) -> dict:
    """같은 날·같은 시장의 시세 단축코드 ↔ 마스터 ISIN 연결과 필드 결측·중복·무거래 행을 센다.

    거래량 0 행은 거래정지로 단정하지 않는다(`vol0_rows`로만 센다). 정지 판정은 공식 정지 기록과의 대조가 필요하다.
    """
    ledger = Ledger(layout.ledger)
    pairs = {"KOSPI": ("stk_bydd_trd", "stk_isu_base_info"), "KOSDAQ": ("ksq_bydd_trd", "ksq_isu_base_info")}
    out = {m: {"days": 0, "days_incomplete": 0, "trade_rows": 0, "master_rows": 0, "joined": 0,
               "unjoined": 0, "conflict": 0, "master_without_trade": 0, "missing_required_trade": 0,
               "missing_required_master": 0, "dup_trade_code": 0, "dup_master_srt": 0,
               "dup_master_isin": 0, "vol0_rows": 0, "bad_ohlc_rows": 0}
           for m in pairs}
    isins: set[str] = set()
    for day in days:
        for mkt, (tr, ms) in pairs.items():
            o = out[mkt]
            recs = [ledger.get(ledger_key(tr, day)), ledger.get(ledger_key(ms, day))]
            if any(r is None or r.get("status") not in COMPLETE for r in recs):
                o["days_incomplete"] += 1
                continue
            if all(r["status"] == "EMPTY" for r in recs):
                continue
            T = _rows(layout, tr, day) if recs[0]["status"] == "OK" else []
            B = _rows(layout, ms, day) if recs[1]["status"] == "OK" else []
            o["days"] += 1
            o["trade_rows"] += len(T)
            o["master_rows"] += len(B)
            by_srt: dict[str, list[dict]] = {}
            for r in B:
                by_srt.setdefault(r.get("ISU_SRT_CD"), []).append(r)
                isins.add(r.get("ISU_CD"))
            o["dup_master_srt"] += sum(1 for v in by_srt.values() if len(v) > 1)
            o["dup_master_isin"] += len(B) - len({r.get("ISU_CD") for r in B})
            o["dup_trade_code"] += len(T) - len({r.get("ISU_CD") for r in T})
            o["missing_required_trade"] += sum(1 for r in T if any(_empty(r.get(f)) for f in REQUIRED_TRADE))
            o["missing_required_master"] += sum(1 for r in B if any(_empty(r.get(f)) for f in REQUIRED_MASTER))
            codes = set()
            for r in T:
                c = r.get("ISU_CD")
                codes.add(c)
                n = len(by_srt.get(c, []))
                o["joined" if n == 1 else ("unjoined" if n == 0 else "conflict")] += 1
                vol = str(r.get("ACC_TRDVOL", "")).replace(",", "")
                if vol == "0":
                    o["vol0_rows"] += 1
                else:
                    try:
                        op, hi, lo, cl = (float(str(r.get(k, "")).replace(",", "")) for k in
                                          ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC"))
                        if not (0 < lo <= min(op, cl) and max(op, cl) <= hi):
                            o["bad_ohlc_rows"] += 1
                    except ValueError:
                        o["bad_ohlc_rows"] += 1
            o["master_without_trade"] += sum(1 for s in by_srt if s not in codes)
    out["distinct_isin"] = len(isins)
    return out
