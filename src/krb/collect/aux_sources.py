"""보조 원천 수집(KRX 시세와 독립): OpenDART 거래소 시장조치 공시 목록, 금융위 주식권리일정, OpenDART 고유번호.

두 기관은 인증키를 URL 쿼리로 받는다. 이 모듈은 URL을 로그·장부·파일 어디에도 남기지 않고,
응답에 키가 들어 있으면 저장하지 않고 중단한다. 서버·프록시 접근 로그에 URL이 남는 위험은 코드로 막을 수 없다.

여기서 받은 공시·일정은 원본일 뿐이다. 거래정지·상장폐지·기업행위·스팩 판정은 하지 않으며
판정 전 상태는 모두 UNKNOWN이다(접수일 rcept_dt는 효력일이 아니다).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
from pathlib import Path
from typing import Callable

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
    weekdays,
)

DART_KEY_ENV = "KRB_OPENDART_API_KEY"
DATAGOKR_KEY_ENV = "KRB_DATAGOKR_SERVICE_KEY"
DART_LIST = "https://opendart.fss.or.kr/api/list.json"
DART_CORPCODE = "https://opendart.fss.or.kr/api/corpCode.xml"
FSC_RIGHTS = "https://apis.data.go.kr/1160100/GetStocRighScheService_V2/getRighExerReasSche_V2"

# OpenDART 응답 status 중 계속하면 안 되는 것(인증·한도·IP). 013은 "조회된 데이터 없음".
DART_STOP = {"010", "011", "012", "020", "021", "800", "901"}
# data.go.kr 오류 코드 중 계속하면 안 되는 것(키 미등록·한도 초과 등).
FSC_STOP = {"20", "22", "30", "31", "32", "33"}


def _key(env: str) -> str:
    v = os.environ.get(env, "")
    if not v:
        raise MissingCredential(f"환경변수 {env}가 없다. 키를 설정한 뒤 다시 실행한다")
    return v


def month_windows(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """달력 월 단위 창. OpenDART는 고유번호 없이 검색하면 3개월로 제한된다(개발가이드)."""
    out, cur = [], start
    while cur <= end:
        nxt = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        out.append((cur, min(end, nxt - dt.timedelta(days=1))))
        cur = nxt
    return out


class _PagedStore:
    def __init__(self, root: Path, name: str):
        self.root = root / "raw" / name
        self.ledger = Ledger(self.root / "_ledger.jsonl")

    def done(self, key: str, path: Path) -> bool:
        rec = self.ledger.get(key)
        if not rec or rec.get("status") not in ("OK", "EMPTY"):
            return False
        if rec["status"] == "EMPTY":
            return True
        return path.exists() and sha256_bytes(path.read_bytes()) == rec.get("sha256")


def collect_dart_i003(data_root: Path, start: dt.date, end: dt.date, fetcher: Fetcher,
                      corp_cls: str = "", log: Callable[[str], None] = print) -> dict:
    """`pblntf_detail_ty=I003` 단독 필터(S2에서 확인: `pblntf_ty=I`와 함께 쓰면 세부유형이 무시됨)."""
    check_window(start, end)
    key = _key(DART_KEY_ENV)
    redact = Redactor([key])
    store = _PagedStore(data_root, "opendart_i003")
    stats = {"pages_ok": 0, "pages_empty": 0, "pages_failed": 0, "skipped": 0, "stopped": None}
    try:
        for a, b in month_windows(start, end):
            page, total_page = 1, 1
            while page <= total_page:
                tag = f"{a:%Y%m%d}_{b:%Y%m%d}_{corp_cls or 'ALL'}_p{page:04d}"
                path = store.root / f"{a:%Y}" / f"{tag}.json"
                rec = store.ledger.get(tag)
                if store.done(tag, path):
                    total_page = rec.get("total_page", total_page)
                    stats["skipped"] += 1
                    page += 1
                    continue
                params = {"bgn_de": f"{a:%Y%m%d}", "end_de": f"{b:%Y%m%d}", "pblntf_detail_ty": "I003",
                          "page_no": str(page), "page_count": "100"}
                if corp_cls:
                    params["corp_cls"] = corp_cls
                resp = fetcher.fetch(f"opendart I003 {tag}",
                                     DART_LIST + "?" + urllib.parse.urlencode({**params, "crtfc_key": key}),
                                     {"Accept": "application/json"})
                if redact.contains(resp.body):
                    raise StopCollection(f"opendart {tag}: 응답에 키가 들어 있어 저장하지 않고 중단한다")
                out = {"key": tag, "params": params, "http_status": resp.status, "transport_error": resp.error,
                       "retrieved_at": now_kst(), "source": "OpenDART list.json", "sha256": sha256_bytes(resp.body)}
                try:
                    doc = json.loads(resp.body.decode("utf-8")) if resp.status == 200 else {}
                except (UnicodeDecodeError, json.JSONDecodeError):
                    doc = {}
                st = doc.get("status")
                if st in DART_STOP:
                    store.ledger.append({**out, "status": "FAILED", "api_status": st})
                    raise StopCollection(f"opendart {tag}: status {st}로 중단한다")
                if st == "000":
                    atomic_write(path, resp.body)
                    total_page = int(doc.get("total_page") or 1)
                    store.ledger.append({**out, "status": "OK", "api_status": st, "rows": len(doc.get("list") or []),
                                         "total_count": doc.get("total_count"), "total_page": total_page,
                                         "path": str(path.relative_to(data_root))})
                    stats["pages_ok"] += 1
                elif st == "013":
                    store.ledger.append({**out, "status": "EMPTY", "api_status": st, "total_page": 0})
                    stats["pages_empty"] += 1
                    break
                else:
                    store.ledger.append({**out, "status": "FAILED", "api_status": st})
                    stats["pages_failed"] += 1
                    log(f"opendart {tag}: 실패 status={st} http={resp.status}")
                    break
                page += 1
    except StopCollection as e:
        stats["stopped"] = str(e)
        log(str(e))
    finally:
        del key
    stats["calls"] = fetcher.calls
    return stats


def _fsc_doc(body: bytes) -> tuple[str | None, dict]:
    """(결과 코드, body). JSON이 아니면(data.go.kr 게이트웨이 XML 오류 등) 코드에 XML 사유를 넣는다."""
    text = body.decode("utf-8", errors="replace")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        for tag in ("returnReasonCode", "resultCode"):
            s = text.find(f"<{tag}>")
            if s >= 0:
                e = text.find(f"</{tag}>", s)
                return text[s + len(tag) + 2:e].strip(), {}
        return None, {}
    resp = doc.get("response", doc)
    return (resp.get("header") or {}).get("resultCode"), resp.get("body") or {}


def collect_fsc_rights(data_root: Path, start: dt.date, end: dt.date, fetcher: Fetcher,
                       rows_per_page: int = 1000, log: Callable[[str], None] = print) -> dict:
    """주식권리일정을 기준일(basDt)별로 받는다. 배정비율·ISIN은 이 API에 없으므로 만들지 않는다."""
    check_window(start, end)
    key = _key(DATAGOKR_KEY_ENV)
    redact = Redactor([key])
    store = _PagedStore(data_root, "fsc_rights_schedule")
    stats = {"pages_ok": 0, "pages_empty": 0, "pages_failed": 0, "skipped": 0, "stopped": None}
    try:
        for day in weekdays(start, end):
            page, total_pages = 1, 1
            while page <= total_pages:
                tag = f"{day:%Y%m%d}_p{page:04d}"
                path = store.root / f"{day:%Y}" / f"{tag}.json"
                rec = store.ledger.get(tag)
                if store.done(tag, path):
                    total_pages = rec.get("total_pages", total_pages)
                    stats["skipped"] += 1
                    page += 1
                    continue
                params = {"pageNo": str(page), "numOfRows": str(rows_per_page), "resultType": "json",
                          "basDt": f"{day:%Y%m%d}"}
                resp = fetcher.fetch(f"fsc rights {tag}",
                                     FSC_RIGHTS + "?" + urllib.parse.urlencode({**params, "serviceKey": key}),
                                     {"Accept": "application/json"})
                if redact.contains(resp.body):
                    raise StopCollection(f"fsc {tag}: 응답에 키가 들어 있어 저장하지 않고 중단한다")
                code, body = _fsc_doc(resp.body) if resp.body else (None, {})
                out = {"key": tag, "params": params, "http_status": resp.status, "transport_error": resp.error,
                       "retrieved_at": now_kst(), "source": "FSC getRighExerReasSche_V2",
                       "sha256": sha256_bytes(resp.body), "api_status": code}
                if code in FSC_STOP:
                    store.ledger.append({**out, "status": "FAILED"})
                    raise StopCollection(f"fsc {tag}: 결과 코드 {code}로 중단한다")
                if resp.status == 200 and code == "00":
                    total = int(body.get("totalCount") or 0)
                    if total == 0:
                        store.ledger.append({**out, "status": "EMPTY", "total_pages": 0})
                        stats["pages_empty"] += 1
                        break
                    total_pages = -(-total // rows_per_page)
                    atomic_write(path, resp.body)
                    store.ledger.append({**out, "status": "OK", "total_count": total, "total_pages": total_pages,
                                         "path": str(path.relative_to(data_root))})
                    stats["pages_ok"] += 1
                else:
                    store.ledger.append({**out, "status": "FAILED"})
                    stats["pages_failed"] += 1
                    log(f"fsc {tag}: 실패 code={code} http={resp.status}")
                    break
                page += 1
    except StopCollection as e:
        stats["stopped"] = str(e)
        log(str(e))
    finally:
        del key
    stats["calls"] = fetcher.calls
    return stats


def collect_dart_corpcode(data_root: Path, fetcher: Fetcher, log: Callable[[str], None] = print) -> dict:
    """OpenDART 고유번호 ZIP 1회. 현재 시점 목록이므로 과거 대응 관계는 검증 전까지 UNKNOWN이다."""
    key = _key(DART_KEY_ENV)
    redact = Redactor([key])
    store = _PagedStore(data_root, "opendart_corpcode")
    resp = fetcher.fetch("opendart corpCode", DART_CORPCODE + "?" + urllib.parse.urlencode({"crtfc_key": key}), {})
    del key
    if redact.contains(resp.body):
        raise StopCollection("opendart corpCode: 응답에 키가 들어 있어 저장하지 않는다")
    retrieved = now_kst()
    rec = {"key": f"corpCode_{retrieved}", "http_status": resp.status, "transport_error": resp.error,
           "retrieved_at": retrieved, "source": "OpenDART corpCode.xml", "sha256": sha256_bytes(resp.body),
           "note": "current snapshot; historical mapping UNKNOWN"}
    if resp.status == 200 and resp.body[:2] == b"PK":
        path = store.root / f"corpCode_{retrieved.replace(':', '')}.zip"
        atomic_write(path, resp.body)
        store.ledger.append({**rec, "status": "OK", "path": str(path.relative_to(data_root))})
        return {"status": "OK", "bytes": len(resp.body)}
    store.ledger.append({**rec, "status": "FAILED"})
    log(f"opendart corpCode: 실패 http={resp.status}")
    return {"status": "FAILED"}
