"""수집기 공통 부품: 기간 상한, 완료 장부, 원자적 저장, 재시도 HTTP, 비밀값 가림."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 데이터 계약 4.1: 현재 단계(Phase 0~2)의 시장 데이터 기준일 상한 C_R.
RESEARCH_CUTOFF = dt.date(2022, 12, 29)
# 데이터 계약 2.3: 원시 데이터 시작일 D_start.
DATA_START = dt.date(2017, 8, 1)


class CutoffViolation(ValueError):
    """C_R 뒤 날짜나 D_start 앞 날짜를 요청했다."""


class MissingCredential(RuntimeError):
    """필요한 인증 환경변수가 없다."""


class StopCollection(RuntimeError):
    """서버 제한·인증 실패처럼 계속하면 안 되는 응답을 받았다."""


def now_kst() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def check_window(start: dt.date, end: dt.date, cutoff: dt.date = RESEARCH_CUTOFF) -> None:
    if start > end:
        raise CutoffViolation("start가 end보다 늦다")
    if end > cutoff:
        raise CutoffViolation(f"end {end.isoformat()}가 컷오프 {cutoff.isoformat()}를 넘는다")
    if start < DATA_START:
        raise CutoffViolation(f"start {start.isoformat()}가 데이터 시작일 {DATA_START.isoformat()}보다 이르다")


def weekdays(start: dt.date, end: dt.date) -> Iterator[dt.date]:
    """월~금 날짜. 휴장일은 하드코딩하지 않는다(AGENTS.md 1절).

    휴장일은 응답이 비어 EMPTY로 기록되고, XKRX 거래일 목록(Gate D12)과의 대조는 품질 검사(Q1·Q2)에서 한다.
    """
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += dt.timedelta(days=1)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    """임시 파일에 쓰고 fsync 뒤 이름을 바꾼다. 중간에 끊기면 `.part`만 남고 완료로 보지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Ledger:
    """append-only JSONL 완료 장부. 같은 키의 마지막 기록이 유효하다."""

    def __init__(self, path: Path):
        self.path = path
        self._last: dict[str, dict] = {}
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        # 끊긴 마지막 줄은 무시한다. 그 키는 다시 수집된다.
                        continue
                    self._last[rec["key"]] = rec

    def get(self, key: str) -> dict | None:
        return self._last.get(key)

    def append(self, rec: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._last[rec["key"]] = rec

    def records(self) -> list[dict]:
        return list(self._last.values())


@dataclasses.dataclass
class Response:
    status: int | None
    body: bytes
    error: str | None = None  # 전송 오류의 예외 종류 이름만. 메시지는 URL을 담을 수 있어 버린다.


# transport(url, headers, timeout) -> Response. 테스트에서 가짜로 바꾼다.
Transport = Callable[[str, dict, float], Response]


def urllib_transport(url: str, headers: dict, timeout: float) -> Response:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Response(r.status, r.read())
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return Response(e.code, body, "HTTPError")
    except Exception as e:  # noqa: BLE001 - 메시지(URL 포함 가능)는 버리고 종류만 남긴다
        return Response(None, b"", type(e).__name__)


class Redactor:
    """비밀값을 문자열·바이트에서 지운다. 로그·장부·원본 저장 전에 쓴다."""

    def __init__(self, secrets: list[str]):
        self.secrets = [s for s in secrets if s]

    def text(self, s: str) -> str:
        for sec in self.secrets:
            s = s.replace(sec, "[REDACTED]")
        return s

    def contains(self, data: bytes) -> bool:
        return any(sec.encode() in data for sec in self.secrets)


@dataclasses.dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_base: float = 2.0
    min_interval: float = 0.5
    stop_statuses: tuple[int, ...] = (401, 403, 429)
    retry_statuses: tuple[int, ...] = (500, 502, 503, 504)


class Fetcher:
    """호출 간격 제한, 제한된 재시도, 중단 응답 처리, 호출 수 상한을 가진 요청기.

    URL은 어디에도 기록하지 않는다. 호출자는 라벨(API·날짜)만 넘긴다.
    """

    def __init__(self, transport: Transport, policy: RetryPolicy, max_calls: int,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 log: Callable[[str], None] = print):
        self.transport = transport
        self.policy = policy
        self.max_calls = max_calls
        self.calls = 0
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None
        self.log = log

    def _wait_interval(self) -> None:
        if self._last_call is not None:
            gap = self._clock() - self._last_call
            if gap < self.policy.min_interval:
                self._sleep(self.policy.min_interval - gap)

    def fetch(self, label: str, url: str, headers: dict, timeout: float = 60.0) -> Response:
        last = Response(None, b"", "NotAttempted")
        for attempt in range(1, self.policy.max_attempts + 1):
            if self.calls >= self.max_calls:
                raise StopCollection(f"이번 실행의 호출 상한 {self.max_calls}회에 도달했다")
            self._wait_interval()
            self.calls += 1
            self._last_call = self._clock()
            last = self.transport(url, headers, timeout)
            if last.status in self.policy.stop_statuses:
                raise StopCollection(f"{label}: HTTP {last.status} 응답으로 중단한다(인증 또는 호출 제한)")
            transient = last.status is None or last.status in self.policy.retry_statuses
            if not transient:
                return last
            if attempt < self.policy.max_attempts:
                wait = self.policy.backoff_base ** attempt
                self.log(f"{label}: 일시 오류(status={last.status}, error={last.error}), {wait:.0f}초 뒤 재시도 {attempt + 1}/{self.policy.max_attempts}")
                self._sleep(wait)
        return last
