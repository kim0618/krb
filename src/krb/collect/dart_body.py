"""OpenDART 공시 본문(document.xml ZIP)에서 거래정지·해제·기간변경·정리매매 사실을 뽑는다 (추출기 V2).

    python -m krb.collect.dart_body --targets targets.csv --out extract.csv

원본 ZIP은 읽기만 한다. 본문에 적힌 날짜·시각만 쓰고 조건부 문구('결정일까지' 등)는
CONDITIONAL로 두며 날짜로 바꾸지 않는다. 공시 접수 시각은 목록·본문에 없어 rcept_time = UNKNOWN.
KRX 대조는 로컬 원본만 쓴다: 본문상 하루 종일 정지인 거래일에 정규장 체결(시가·고가·저가 > 0)이
있거나, 정리매매 기간과 시세 존재일이 다르면 CONFLICT.

V2 수정(V1 대비): UTF-8 본문 우선 해석, 기간변경의 시작 시각 저장, 조건 문구가 섞인 해제일은
CONDITIONAL, 장중 해제('30분 경과', '장종료시까지')는 INTRADAY, 시작 날짜만 있고 해제가 미확정이면
하루 종일 정지로 가정하지 않음.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import html
import json
import re
import zipfile
from pathlib import Path

from .calendar_d12 import default_sessions_path, load_sessions

FIELDS = ("fmt", "halt_start", "halt_start_time", "halt_start_status", "halt_end", "halt_end_time",
          "halt_end_status", "end_condition_text", "period_before", "period_after", "dt_period", "dt_role",
          "reason", "evidence")
TRADE_API = {"KOSPI": "stk_bydd_trd", "KOSDAQ": "ksq_bydd_trd"}

D = r"(?:'?\d{2}|\d{4})\s*[.\-년]\s*\d{1,2}\s*[.\-월]\s*\d{1,2}\s*일?"


def body_text(raw: bytes) -> str:
    """ZIP 안 XML 1개를 ' | '로 구분된 한 줄 텍스트로 바꾼다."""
    try:  # 선언과 달리 UTF-8인 본문(2022년 일부)이 있어 UTF-8을 먼저 시도한다
        t = raw.decode("utf-8")
    except UnicodeDecodeError:
        t = raw.decode("cp949", "replace")
    t = re.sub(r"<style.*?</style>", "", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " | ", t)
    t = html.unescape(" ".join(t.split()))
    return re.sub(r"(\|\s*)+", "| ", t)


def zip_body(path: Path) -> bytes:
    with zipfile.ZipFile(path) as z:
        return z.read(z.namelist()[0])


def pdate(s):
    m = re.search(r"('?)(\d{2}|\d{4})\s*[.\-년]\s*(\d{1,2})\s*[.\-월]\s*(\d{1,2})", s or "")
    if not m:
        return None
    y = int(m.group(2))
    y = y + 2000 if y < 100 else y
    try:
        return dt.date(y, int(m.group(3)), int(m.group(4)))
    except ValueError:
        return None


def ptime(s):
    m = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?!\d)", s or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def point(cell_date, cell_time):
    """(date, time, status). status: EXACT_DATETIME / DATE_ONLY / CONDITIONAL / INTRADAY / UNKNOWN."""
    txt = f'{cell_date or ""} {cell_time or ""}'.strip()
    if re.search(r"30분|경과시점|장종료시", txt):
        return None, None, "INTRADAY"
    if re.search(r"결정일|통지|확인시|해소|까지", txt):  # 날짜가 섞여 있어도 조건부
        return None, None, "CONDITIONAL"
    d, t = pdate(txt), ptime(txt)
    if d and t:
        return d, t, "EXACT_DATETIME"
    if d:
        return d, None, "DATE_ONLY"
    if re.search(r"까지|시까지|결정|통지|확인|해소", txt) and txt.strip("- "):
        return None, None, "CONDITIONAL"
    return None, None, "UNKNOWN"


def _grab(rx, t):
    m = re.search(rx, t)
    return (m, t[max(0, m.start()):m.end()][:300]) if m else (None, "")


def extract(t: str) -> dict:
    o = {k: "" for k in FIELDS}
    head = t[:200]
    m, ev = _grab(r"매매거래정지 일시 \| (.+?)\| 4\. 매매거래정지 해제일시 \| (.+?)\| 5\.", t)
    if m:  # KOSPI: 매매거래정지 및 정지해제
        o["fmt"] = "KOSPI_HALT_RELEASE"
        a, b = point(m.group(1), ""), point(m.group(2), "")
        o.update(halt_start=a[0] or "", halt_start_time=a[1] or "", halt_start_status=a[2],
                 halt_end=b[0] or "", halt_end_time=b[1] or "", halt_end_status=b[2])
        if b[2] in ("CONDITIONAL", "UNKNOWN", "INTRADAY"):
            o["end_condition_text"] = m.group(2).replace("|", " ").strip()
        r = re.search(r"매매거래정지 (?:및 해제 )?사유 \| ([^|]+)", t)
        o["reason"] = r.group(1).strip() if r else ""
        o["evidence"] = ev
        return o
    m, ev = _grab(r"가\.\s*정지일시 \| ([^|]+)\| ([^|]+)\| 나\.\s*만료일시 \| ([^|]+)\|", t)
    if m:
        o["fmt"] = "KOSDAQ_HALT"
        a, b = point(m.group(1), m.group(2)), point(m.group(3), "")
        o.update(halt_start=a[0] or "", halt_start_time=a[1] or "", halt_start_status=a[2],
                 halt_end=b[0] or "", halt_end_status=b[2])
        if b[2] in ("CONDITIONAL", "UNKNOWN", "INTRADAY"):
            o["end_condition_text"] = m.group(3).strip()
        r = re.search(r"정지사유 \| ([^|]+)", t)
        o["reason"] = r.group(1).strip() if r else ""
        o["evidence"] = ev
        return o
    m, ev = _grab(r"해제일시 \| ([^|]+)\| ([^|]+)\|", t)
    if m and "정지해제" in head:
        o["fmt"] = "KOSDAQ_RELEASE"
        b = point(m.group(1), m.group(2))
        o.update(halt_end=b[0] or "", halt_end_time=b[1] or "", halt_end_status=b[2])
        r = re.search(r"해제사유 \| ([^|]+)", t)
        o["reason"] = r.group(1).strip() if r else ""
        o["evidence"] = ev
        return o
    m, ev = _grab(r"가\.\s*변경전 \| ([^|]+)\| 나\.\s*변경후 \| ([^|]+)\|", t)
    if m:
        o["fmt"] = "PERIOD_CHANGE"
        o["period_before"], o["period_after"] = m.group(1).strip(), m.group(2).strip()
        parts = re.split(r"~", m.group(2), maxsplit=1)
        a = point(parts[0], "")
        b = point(parts[1] if len(parts) > 1 else "", "")
        o.update(halt_start=a[0] or "", halt_start_time=a[1] or "", halt_start_status=a[2],
                 halt_end=b[0] or "", halt_end_status=b[2])
        if b[2] in ("CONDITIONAL", "UNKNOWN", "INTRADAY"):
            o["end_condition_text"] = (parts[1] if len(parts) > 1 else "").strip()
        r = re.search(r"변경사유 \| ([^|]+)", t)
        o["reason"] = r.group(1).strip() if r else ""
        o["evidence"] = ev
        return o
    if "정리매매" in t:
        o["fmt"] = "DELIST_TRADING_TEXT"
        t = re.sub(r"\s*\|\s*", "", t)  # 줄바꿈으로 쪼개진 날짜·기간을 잇는다(정리매매 서술형에만)
        rngs = [(mm.start(), mm.group(1), mm.group(2), mm.end()) for mm in re.finditer(rf"({D})\s*~\s*({D})", t)]
        rngs = [r for r in rngs if "정리매매" in t[max(0, r[0] - 40):r[0] + 60]]
        role = "HOLD" if "보류" in head else ("RESUMED" if "재개" in head else ("START" if "개시" in head else "OTHER"))
        o["dt_role"] = role
        if rngs:
            hit = [r for r in rngs if re.search("재개|개시", t[r[3]:r[3] + 40])]
            pick = hit[-1] if hit else rngs[-1]
            a, b = pdate(pick[1]), pdate(pick[2])
            o["dt_period"] = f"{a}~{b}" if a and b else ""
            o["evidence"] = t[max(0, pick[0] - 80):pick[0] + 60]
            if role == "HOLD":  # 보류 공시의 기간은 원래 예정·진행 기간이지 확정 기간이 아니다
                o["dt_role"] = "HOLD(원래기간)"
        else:
            o["evidence"] = t[:250]
        o["reason"] = "정리매매 " + role
        return o
    o["fmt"] = "UNPARSED"
    o["evidence"] = t[:250]
    return o


class KrxRows:
    """로컬 KRX 일별매매정보 조회(대조용)."""

    def __init__(self, data_root: Path, sessions: list[dt.date]):
        self.root, self.sess = data_root / "raw" / "krx", sessions

    def row(self, api, d, code):
        p = self.root / api / f"{d:%Y}" / f"{d:%Y%m%d}.json"
        if not p.exists():
            return "NOFILE"
        with p.open(encoding="utf-8") as f:
            for r in json.load(f)["OutBlock_1"]:
                if r["ISU_CD"] == code:
                    return r
        return None

    def next(self, d):
        i = bisect.bisect_right(self.sess, d)
        return self.sess[i] if i < len(self.sess) else None

    def prev(self, d):
        i = bisect.bisect_left(self.sess, d) - 1
        return self.sess[i] if i >= 0 else None


def krx_check(o: dict, mkt: str | None, code: str | None, k: KrxRows) -> tuple[str, str]:
    api = TRADE_API.get(mkt or "")
    if not api or not code:
        return "NO_LINK", ""
    sess = k.sess
    if o["fmt"] == "DELIST_TRADING_TEXT" and o["dt_period"] and o["dt_role"] in ("RESUMED", "START"):
        a, b = (dt.date.fromisoformat(x) for x in o["dt_period"].split("~"))
        days = [d for d in sess if a <= d <= b]
        miss = [d.isoformat() for d in days if not isinstance(k.row(api, d, code), dict)]
        after = k.next(b)
        aft = k.row(api, after, code) if after else "NOFILE"
        if miss:
            return "CONFLICT", f"정리매매일 시세 없음 {miss}"
        if isinstance(aft, dict):
            return "CONFLICT", f"정리매매 종료 다음 거래일({after})에도 시세 있음"
        return "CONSISTENT", f"{len(days)}거래일 시세 존재, {after} 이후 없음"
    if not o["halt_start"] and not o["halt_end"]:
        return "NOT_CHECKED", ""
    # 하루 종일 정지된 거래일: 시작이 장 시작 전(≤09:00)이면 그날부터, 장중·장후면 다음 거래일부터
    full = []
    if o["halt_start"]:
        s = o["halt_start"] if isinstance(o["halt_start"], dt.date) else dt.date.fromisoformat(str(o["halt_start"]))
        t = o["halt_start_time"]
        if o["halt_end_status"] == "INTRADAY":
            return "NO_FULL_HALT_DAY", "해제가 장중(30분 경과 등)이라 하루 종일 정지가 아님"
        if not t and not o["halt_end"]:  # 시작 날짜만 있고 해제 미확정이면 그날 장중 시작일 수 있다
            return "NOT_CHECKED_CONDITIONAL", "시작 시각 미기재, 해제 조건부/미상"
        if t and t > "09:00" and not o["halt_end"] and o["halt_end_status"] in ("CONDITIONAL", "UNKNOWN"):
            return "NOT_CHECKED_CONDITIONAL", "장중·장후 시작, 해제 조건부/미상: 다음 거래일 정지 여부를 가정하지 않음"
        first = s if (not t or t <= "09:00") else k.next(s)
        if first and s not in sess and not t:
            first = k.next(k.prev(s) or s)
        last = None
        if o["halt_end"]:
            e = o["halt_end"] if isinstance(o["halt_end"], dt.date) else dt.date.fromisoformat(str(o["halt_end"]))
            last = k.prev(e)
        if first:
            if last:
                full = [d for d in sess if first <= d <= last]
            elif o["fmt"] != "KOSPI_HALT_RELEASE":
                full = [first] if first in sess else []
    if not full:
        return "NO_FULL_HALT_DAY", ""
    conf, off = [], []
    for d in full[:40]:
        r = k.row(api, d, code)
        if isinstance(r, dict):
            try:
                v = float(r["ACC_TRDVOL"].replace(",", ""))
                ohl = [float(r[x].replace(",", "")) for x in ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC")]
            except ValueError:
                continue
            if v > 0 and min(ohl) > 0:
                conf.append(d.isoformat())
            elif v > 0:
                off.append(d.isoformat())
    if conf:
        return "CONFLICT", f"정지일 정규장 체결 {conf[:5]}"
    return "CONSISTENT", f"정지일 {len(full)}일 확인" + (f", 시가·고가·저가 0·거래량>0 {off[:3]}" if off else "")


def run(data_root: Path, sessions: list[dt.date], targets_csv: Path | None, out_csv: Path) -> list[dict]:
    targets = {}
    if targets_csv and targets_csv.exists():
        with targets_csv.open(encoding="utf-8") as f:
            targets = {r["rcept_no"]: r for r in csv.DictReader(f)}
    i003 = {}
    for p in sorted((data_root / "processed" / "opendart_i003").glob("*/*_classified.csv")):
        with p.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                i003[r["rcept_no"]] = r
    root = data_root / "raw" / "opendart_document"
    ledger = {}
    with (root / "_ledger.jsonl").open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            ledger[r["key"]] = r
    k = KrxRows(data_root, sessions)
    out = []
    for rn, rec in ledger.items():
        if rec.get("status") != "OK":
            continue
        meta = i003.get(rn, {})
        o = extract(body_text(zip_body(data_root / rec["path"])))
        st, note = krx_check(o, meta.get("market_then"), meta.get("stock_code"), k)
        out.append({"rcept_no": rn, "rcept_dt": meta.get("rcept_dt"), "rcept_time": "UNKNOWN",
                    "priority": targets.get(rn, {}).get("priority", "S3-2"), "market_then": meta.get("market_then"),
                    "stock_code": meta.get("stock_code"), "isin": meta.get("isin"), "category": meta.get("category"),
                    "report_nm": meta.get("report_nm"), **{x: str(v) for x, v in o.items()}, "krx_check": st,
                    "krx_note": note, "body_sha256": rec["sha256"]})
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["rcept_no"])
        w.writeheader()
        w.writerows(out)
    return out


def main(argv=None) -> int:
    from .__main__ import find_repo_root
    p = argparse.ArgumentParser(prog="python -m krb.collect.dart_body")
    p.add_argument("--data-root", type=Path, default=None)
    p.add_argument("--sessions", type=Path, default=None)
    p.add_argument("--targets", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    root = a.data_root or find_repo_root(Path.cwd()) / "data"
    out = run(root, load_sessions(a.sessions or default_sessions_path(root)), a.targets, a.out)
    print(json.dumps({"rows": len(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
