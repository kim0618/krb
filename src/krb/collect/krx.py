"""KRX OpenAPI 4개 서비스의 날짜별 원본 수집.

공식 개발 명세서(KRX OpenAPI 서비스 이용 > 개발 명세서, 2026-10-22 확인):
  Server endpoint url : https://data-dbg.krx.co.kr/svc/apis/sto/{서비스}
  request              : basDd(string, 기준일자 YYYYMMDD)
  인증                  : Request 헤더 AUTH_KEY
  response             : {"OutBlock_1": [...]}
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
from pathlib import Path
from typing import Callable, Iterable

from .core import (
    Fetcher,
    Ledger,
    MissingCredential,
    Redactor,
    StopCollection,
    atomic_write,
    check_window,
    now_kst,
    sha256_bytes,
    sha256_file,
    weekdays,
)

ENDPOINT_BASE = "https://data-dbg.krx.co.kr/svc/apis/sto/"
KEY_ENV = "KRB_KRX_OPENAPI_KEY"
SOURCE = "KRX OpenAPI"

APIS = {
    "stk_bydd_trd": {"market": "KOSPI", "kind": "trade"},
    "ksq_bydd_trd": {"market": "KOSDAQ", "kind": "trade"},
    "stk_isu_base_info": {"market": "KOSPI", "kind": "master"},
    "ksq_isu_base_info": {"market": "KOSDAQ", "kind": "master"},
}

COMPLETE = {"OK", "EMPTY"}


@dataclasses.dataclass
class Layout:
    data_root: Path

    @property
    def raw(self) -> Path:
        return self.data_root / "raw" / "krx"

    @property
    def ledger(self) -> Path:
        return self.raw / "_ledger.jsonl"

    @property
    def failures(self) -> Path:
        return self.raw / "_failures"

    @property
    def orphans(self) -> Path:
        return self.raw / "_orphans"

    def raw_file(self, api: str, day: dt.date) -> Path:
        return self.raw / api / f"{day:%Y}" / f"{day:%Y%m%d}.json"

    def processed_file(self, api: str, day: dt.date) -> Path:
        return self.data_root / "processed" / "krx" / api / f"{day:%Y}" / f"{day:%Y%m%d}.csv"


def ledger_key(api: str, day: dt.date) -> str:
    return f"{api}:{day:%Y%m%d}"


def is_complete(layout: Layout, ledger: Ledger, api: str, day: dt.date) -> bool:
    """장부가 OK/EMPTY이고 원본 파일이 있으며 SHA-256이 장부와 같을 때만 완료다."""
    rec = ledger.get(ledger_key(api, day))
    if not rec or rec.get("status") not in COMPLETE:
        return False
    path = layout.raw_file(api, day)
    return path.exists() and sha256_file(path) == rec.get("sha256")


def classify(api: str, day: dt.date, status: int | None, body: bytes) -> tuple[str, int, str]:
    """(상태, 행 수, 설명). 상태: OK / EMPTY / FAILED."""
    if status != 200:
        return "FAILED", 0, f"http_status={status}"
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "FAILED", 0, "json_parse_error"
    rows = doc.get("OutBlock_1") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        keys = sorted(doc.keys()) if isinstance(doc, dict) else []
        return "FAILED", 0, f"no_OutBlock_1 keys={keys}"
    if not rows:
        # 휴장일 후보. 실제 거래일인데 비었는지는 Q1·Q2(XKRX 대조)에서 판정한다.
        return "EMPTY", 0, "empty_OutBlock_1"
    if APIS[api]["kind"] == "trade":
        want = f"{day:%Y%m%d}"
        bad = sum(1 for r in rows if r.get("BAS_DD") != want)
        if bad:
            return "FAILED", len(rows), f"bas_dd_mismatch rows={bad}"
    return "OK", len(rows), ""


def plan(start: dt.date, end: dt.date, apis: Iterable[str]) -> list[tuple[str, dt.date]]:
    check_window(start, end)
    return [(api, day) for day in weekdays(start, end) for api in apis]


def _auth_headers(network_secret: bool) -> tuple[dict, list[str]]:
    if network_secret:
        # 클라우드 Network secret이 프록시에서 AUTH_KEY를 넣는 방식. 이 프로세스는 키를 모른다.
        return {"Accept": "application/json"}, []
    key = os.environ.get(KEY_ENV, "")
    if not key:
        raise MissingCredential(f"환경변수 {KEY_ENV}가 없다. 키를 설정한 뒤 다시 실행한다")
    return {"Accept": "application/json", "AUTH_KEY": key}, [key]


def collect(layout: Layout, start: dt.date, end: dt.date, fetcher: Fetcher,
            apis: Iterable[str] = tuple(APIS), network_secret: bool = False,
            log: Callable[[str], None] = print) -> dict:
    apis = list(apis)
    for api in apis:
        if api not in APIS:
            raise ValueError(f"알 수 없는 API {api}")
    jobs = plan(start, end, apis)
    headers, secrets = _auth_headers(network_secret)
    redact = Redactor(secrets)
    ledger = Ledger(layout.ledger)
    stats = {"planned": len(jobs), "skipped_complete": 0, "ok": 0, "empty": 0, "failed": 0,
             "orphans_moved": 0, "calls": 0, "stopped": None}
    try:
        for api, day in jobs:
            if is_complete(layout, ledger, api, day):
                stats["skipped_complete"] += 1
                continue
            path = layout.raw_file(api, day)
            if path.exists():
                # 장부에 없거나 해시가 다른 파일: 원본을 덮어쓰지 않고 격리한다.
                dest = layout.orphans / api / f"{day:%Y%m%d}.{now_kst().replace(':', '')}.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, dest)
                stats["orphans_moved"] += 1
            label = f"{api} {day:%Y-%m-%d}"
            url = f"{ENDPOINT_BASE}{api}?basDd={day:%Y%m%d}"
            resp = fetcher.fetch(label, url, headers)
            del url
            retrieved_at = now_kst()
            if redact.contains(resp.body):
                ledger.append({"key": ledger_key(api, day), "api": api, "bas_dd": f"{day:%Y%m%d}",
                               "status": "FAILED", "note": "key_echoed_in_response_not_saved",
                               "http_status": resp.status, "retrieved_at": retrieved_at})
                raise StopCollection(f"{label}: 응답에 인증키가 들어 있어 저장하지 않고 중단한다")
            status, rows, note = classify(api, day, resp.status, resp.body)
            rec = {"key": ledger_key(api, day), "api": api, "market": APIS[api]["market"],
                   "bas_dd": f"{day:%Y%m%d}", "status": status, "rows": rows,
                   "http_status": resp.status, "transport_error": resp.error, "note": note,
                   "bytes": len(resp.body), "sha256": sha256_bytes(resp.body),
                   "retrieved_at": retrieved_at, "source": SOURCE,
                   "endpoint": f"{ENDPOINT_BASE}{api}", "request": {"basDd": f"{day:%Y%m%d}"}}
            if status in COMPLETE:
                atomic_write(path, resp.body)
                rec["path"] = str(path.relative_to(layout.data_root))
                stats["ok" if status == "OK" else "empty"] += 1
            else:
                if resp.body:
                    fpath = layout.failures / api / f"{day:%Y%m%d}.{retrieved_at.replace(':', '')}.body"
                    atomic_write(fpath, resp.body)
                    rec["failure_body"] = str(fpath.relative_to(layout.data_root))
                stats["failed"] += 1
                log(f"{label}: 실패 {note}")
            ledger.append(rec)
    except StopCollection as e:
        stats["stopped"] = str(e)
        log(str(e))
    finally:
        stats["calls"] = fetcher.calls
    return stats


def verify(layout: Layout, start: dt.date | None = None, end: dt.date | None = None,
           apis: Iterable[str] = tuple(APIS)) -> dict:
    """장부와 원본 파일의 일치, 남은 `.part`, 격리 파일, 미완료 날짜를 센다."""
    ledger = Ledger(layout.ledger)
    out = {"complete": 0, "ok": 0, "empty": 0, "failed_or_missing": [], "hash_mismatch": [],
           "file_missing": [], "part_files": [], "orphans": 0, "rows_by_api": {}}
    for p in layout.raw.rglob("*.part"):
        out["part_files"].append(str(p.relative_to(layout.data_root)))
    if layout.orphans.exists():
        out["orphans"] = sum(1 for _ in layout.orphans.rglob("*.json"))
    if start and end:
        jobs = plan(start, end, apis)
    else:
        jobs = [(r["api"], dt.datetime.strptime(r["bas_dd"], "%Y%m%d").date()) for r in ledger.records()]
    for api, day in jobs:
        rec = ledger.get(ledger_key(api, day))
        path = layout.raw_file(api, day)
        if not rec or rec.get("status") not in COMPLETE:
            out["failed_or_missing"].append(ledger_key(api, day))
            continue
        if not path.exists():
            out["file_missing"].append(ledger_key(api, day))
            continue
        if sha256_file(path) != rec.get("sha256"):
            out["hash_mismatch"].append(ledger_key(api, day))
            continue
        out["complete"] += 1
        out["ok" if rec["status"] == "OK" else "empty"] += 1
        out["rows_by_api"][api] = out["rows_by_api"].get(api, 0) + rec.get("rows", 0)
    return out
