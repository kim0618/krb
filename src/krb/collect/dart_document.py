"""OpenDART 공시서류원본파일(document.xml) 소량 수집.

    python -m krb.collect.dart_document --max-calls 20 <rcept_no> [<rcept_no> ...]

공식 개발가이드(DS001 공시서류원본파일): GET /api/document.xml, crtfc_key·rcept_no, 응답 ZIP(binary).
status 014는 "파일이 존재하지 않습니다". 키는 URL 쿼리로만 받으므로 URL은 어디에도 남기지 않는다.
- 원본: data/raw/opendart_document/<YYYY>/<rcept_no>.zip, 장부: 같은 폴더 _ledger.jsonl
- 장부에 이미 있는 접수번호는 성공·실패 모두 다시 요청하지 않는다(무제한 재시도 금지).
- 접수일이 RESEARCH 컷오프(2022-12-29) 뒤면 요청하지 않는다.
"""

from __future__ import annotations

import argparse
import io
import json
import urllib.parse
import zipfile
from pathlib import Path
from typing import Callable, Iterable

from .aux_sources import DART_KEY_ENV, DART_STOP, _key
from .core import (RESEARCH_CUTOFF, Fetcher, Ledger, Redactor, RetryPolicy, StopCollection, atomic_write, now_kst,
                   sha256_bytes, urllib_transport)

DART_DOCUMENT = "https://opendart.fss.or.kr/api/document.xml"
SOURCE = "OpenDART document.xml"


def collect_documents(data_root: Path, rcepts: Iterable[str], fetcher: Fetcher,
                      log: Callable[[str], None] = print) -> dict:
    root = data_root / "raw" / "opendart_document"
    ledger = Ledger(root / "_ledger.jsonl")
    key = _key(DART_KEY_ENV)
    redact = Redactor([key])
    stats = {"ok": 0, "failed": 0, "skipped_done": 0, "skipped_failed_before": 0, "skipped_after_cutoff": 0,
             "stopped": None}
    try:
        for rn in rcepts:
            if rn[:8] > f"{RESEARCH_CUTOFF:%Y%m%d}":
                stats["skipped_after_cutoff"] += 1
                continue
            rec = ledger.get(rn)
            if rec:
                stats["skipped_done" if rec.get("status") == "OK" else "skipped_failed_before"] += 1
                continue
            if fetcher.calls >= fetcher.max_calls:
                stats["stopped"] = "call cap reached"
                break
            resp = fetcher.fetch(f"opendart document {rn}",
                                 DART_DOCUMENT + "?" + urllib.parse.urlencode({"crtfc_key": key, "rcept_no": rn}), {})
            if redact.contains(resp.body):
                raise StopCollection(f"opendart document {rn}: 응답에 키가 들어 있어 저장하지 않고 중단한다")
            out = {"key": rn, "params": {"rcept_no": rn}, "http_status": resp.status, "transport_error": resp.error,
                   "retrieved_at": now_kst(), "source": SOURCE, "sha256": sha256_bytes(resp.body),
                   "bytes": len(resp.body)}
            if resp.status == 200 and resp.body[:2] == b"PK":
                path = root / rn[:4] / f"{rn}.zip"
                atomic_write(path, resp.body)
                names = zipfile.ZipFile(io.BytesIO(resp.body)).namelist()
                ledger.append({**out, "status": "OK", "path": str(path.relative_to(data_root)), "members": names})
                stats["ok"] += 1
                continue
            txt = resp.body[:400].decode("utf-8", "replace")
            st = txt.split("<status>")[1].split("</status>")[0] if "<status>" in txt else None
            ledger.append({**out, "status": "FAILED", "api_status": st})
            stats["failed"] += 1
            log(f"opendart document {rn}: 실패 status={st} http={resp.status}")
            if st in DART_STOP:
                raise StopCollection(f"opendart document {rn}: status {st}로 중단한다")
    except StopCollection as e:
        stats["stopped"] = str(e)
        log(str(e))
    finally:
        del key
    stats["calls"] = fetcher.calls
    return stats


def main(argv=None) -> int:
    from .__main__ import find_repo_root
    p = argparse.ArgumentParser(prog="python -m krb.collect.dart_document")
    p.add_argument("--data-root", type=Path, default=None)
    p.add_argument("--max-calls", type=int, required=True, help="이번 실행의 호출 상한(재시도 없음)")
    p.add_argument("--min-interval", type=float, default=1.0)
    p.add_argument("rcept_no", nargs="+")
    a = p.parse_args(argv)
    root = a.data_root or find_repo_root(Path.cwd()) / "data"
    f = Fetcher(urllib_transport, RetryPolicy(max_attempts=1, min_interval=a.min_interval), max_calls=a.max_calls)
    print(json.dumps(collect_documents(root, a.rcept_no, f), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
