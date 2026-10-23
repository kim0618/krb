"""KR-6 보조 도구 테스트(분류·본문 추출·KIND·내보내기·이전). 외부 네트워크를 쓰지 않는다."""

import datetime as dt
import io
import json
import tarfile
import zipfile

import pytest

from krb.collect import dart_body, dart_document, dart_i003, export, handoff, kind, krx
from krb.collect.aux_sources import DART_KEY_ENV
from krb.collect.core import Fetcher, Ledger, Response, RetryPolicy

FAKE_KEY = "FAKEDARTKEY0123456789abcdefFAKEDARTKEY01"


def write_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def master_rows(*codes):
    return {"OutBlock_1": [{"ISU_CD": f"KR7{c}000", "ISU_SRT_CD": c, "ISU_ABBRV": f"N{c}", "SECUGRP_NM": "주권",
                            "KIND_STKCERT_TP_NM": "보통주"} for c in codes]}


def trade_rows(*codes, vol="10", px="100"):
    return {"OutBlock_1": [{"ISU_CD": c, "ISU_NM": f"N{c}", "TDD_OPNPRC": px, "TDD_HGPRC": px, "TDD_LWPRC": px,
                            "TDD_CLSPRC": px, "ACC_TRDVOL": vol, "ACC_TRDVAL": "1000"} for c in codes]}


# --- I003 분류·연결 ------------------------------------------------------------

@pytest.mark.parametrize("title,cat", [
    ("주권매매거래정지기간변경(개선기간부여)", "HALT_PERIOD_CHANGE"),
    ("[기재정정]주권매매거래정지해제", "HALT_RELEASE"),
    ("매매거래정지및정지해제(중요내용공시)", "HALT_RELEASE"),
    ("주권매매거래정지(풍문 또는 보도 관련)", "HALT"),
    ("기타시장안내(정리매매 보류 관련)", "DELIST_TRADING"),
    ("기타시장안내(상장폐지우려예고)", "DELIST"),
    ("기타시장안내(최대주주의보호예수관련)", "OTHER_MARKET_NOTICE"),
    ("권리락(무상증자)", "EX_RIGHTS_DIVIDEND"),
    ("기업설명회(IR)개최(안내공시)", "OTHER"),
])
def test_i003_title_classification(title, cat):
    assert dart_i003.classify(title) == cat


def test_i003_link_uses_krx_master_not_corp_cls(tmp_path):
    root = tmp_path / "data"
    d1 = dt.date(2019, 1, 2)
    write_json(root / "raw/krx/stk_isu_base_info/2019/20190102.json", master_rows("000001"))
    write_json(root / "raw/krx/ksq_isu_base_info/2019/20190102.json", master_rows("100001"))
    m = dart_i003.Masters(root, [d1])
    # 상폐 회사(corp_cls=E)도 당시 마스터에 있으면 그 시장으로 연결된다
    assert m.link("100001", d1)[:3] == ("LINKED_SAME_DAY", "KOSDAQ", "KR7100001000")
    # 휴장일 접수는 직전 거래일 마스터로
    assert m.link("000001", dt.date(2019, 1, 5))[:2] == ("LINKED_PREV_SESSION", "KOSPI")
    assert m.link("000001", dt.date(2019, 1, 1))[0] == "NO_MASTER_FILE"
    assert m.link("", d1)[0] == "NO_STOCK_CODE"
    assert m.link("999999", d1)[0] == "NOT_IN_KOSPI_KOSDAQ_MASTER"
    assert dart_i003.months("201711", "201802") == ["201711", "201712", "201801", "201802"]


# --- 본문 추출 V2 --------------------------------------------------------------

@pytest.mark.parametrize("txt,status", [
    ("2018-10-04 | 16:12", "EXACT_DATETIME"),
    ("2017-08-30 | -", "DATE_ONLY"),
    ("2017년 03월 30일", "DATE_ONLY"),
    ("개선기간 종료('18.10.31)후 상장폐지 여부 결정일까지", "CONDITIONAL"),  # 날짜가 섞여도 조건부
    ("상장예비심사결과 통지일까지", "CONDITIONAL"),
    ("정규시장 매매거래 개시시점부터 30분 경과시점까지", "INTRADAY"),
    ("장종료시까지", "INTRADAY"),
    ("-", "UNKNOWN"),
])
def test_point_status(txt, status):
    assert dart_body.point(txt, "")[2] == status


def test_conditional_end_is_never_turned_into_a_date():
    d, t, st = dart_body.point("2017년 08월 14일 17:34:00~ 개선기간 종료('18.10.31)후 결정일까지".split("~")[1], "")
    assert (d, t, st) == (None, None, "CONDITIONAL")


KOSPI_TXT = ("| 매매거래정지 및 정지해제(중요내용공시) | 1. 종목명 | (주)삼호 주권 | 3. 매매거래정지 일시 | 2020-03-27 | 16:35 "
             "| 4. 매매거래정지 해제일시 | 2020-03-30 | 09:00 | 5. 매매거래정지 사유 | 중요내용공시(회사합병결정) | ")
KOSDAQ_HALT = ("| 주권매매거래정지 | 1.대상종목 | 웹케시(주) | 2.정지사유 | 무상증자 | 3.정지기간 | 가.정지일시 | 2021-04-19 "
               "| 16:43:00 | 나.만료일시 | 장종료시까지 | 4.근거규정 | x | ")
KOSDAQ_RELEASE = "| 주권매매거래정지해제 | 1.대상종목 | x | 2.해제사유 | 승인 | 3.해제일시 | 2017-09-01 | - | 4.근거규정 | "
PERIOD = ("| 주권매매거래정지 기간변경 | 2.변경사유 | 개선기간 부여 | 3.정지기간 | 가.변경전 | 2017년 08월 14일 17:34:00~ 결정일까지 "
          "| 나.변경후 | 2017년 08월 14일 17:34:00~ 개선기간 종료('18.10.31)후 상장폐지 여부 결정일까지 | 4.근거규정 | ")
RESUMED = ("| 기타시장안내(가처분 기각결정에 따른 정리매매절차 재개) | 동사의 주권은 '18.09.28 ~ '18.10.05 기간 동안 정리매매가 "
           "진행되었으며 | - 금일 정리매매('18.10. | 10 ~ '18.10.11) 등 상장폐지 절차가 재개됨을 안내드립니다. |")
HOLD = "| 기타시장안내(정리매매 보류) | 정리매매(2018.09.28~2018.10.10)가 진행 중에 가처분 인용으로 보류 |"


def test_extract_formats():
    o = dart_body.extract(KOSPI_TXT)
    assert (o["fmt"], str(o["halt_start"]), o["halt_start_time"], str(o["halt_end"]), o["halt_end_time"]) == \
        ("KOSPI_HALT_RELEASE", "2020-03-27", "16:35", "2020-03-30", "09:00")
    assert o["reason"] == "중요내용공시(회사합병결정)"
    o = dart_body.extract(KOSDAQ_HALT)
    assert (o["fmt"], o["halt_start_time"], o["halt_end_status"]) == ("KOSDAQ_HALT", "16:43", "INTRADAY")
    o = dart_body.extract(KOSDAQ_RELEASE)
    assert (o["fmt"], str(o["halt_end"]), o["halt_end_status"]) == ("KOSDAQ_RELEASE", "2017-09-01", "DATE_ONLY")
    o = dart_body.extract(PERIOD)
    assert (o["fmt"], o["halt_start_time"], o["halt_end"], o["halt_end_status"]) == \
        ("PERIOD_CHANGE", "17:34", "", "CONDITIONAL")
    o = dart_body.extract(RESUMED)  # 줄바꿈으로 쪼개진 재개 기간을 고른다
    assert (o["dt_role"], o["dt_period"]) == ("RESUMED", "2018-10-10~2018-10-11")
    o = dart_body.extract(HOLD)  # 보류 공시의 기간은 확정 기간이 아니다
    assert o["dt_role"] == "HOLD(원래기간)"
    assert dart_body.extract("| 기업설명회 개최 |")["fmt"] == "UNPARSED"


def test_body_text_prefers_utf8_then_cp949():
    s = "<P>주권매매거래정지</P>"
    assert "주권매매거래정지" in dart_body.body_text(s.encode("utf-8"))
    assert "주권매매거래정지" in dart_body.body_text(s.encode("cp949"))


def test_krx_check_delist_trading_consistent_and_conflict(tmp_path):
    root = tmp_path / "data"
    days = [dt.date(2018, 10, 10), dt.date(2018, 10, 11), dt.date(2018, 10, 12)]
    for d in days[:2]:
        write_json(root / f"raw/krx/ksq_bydd_trd/2018/{d:%Y%m%d}.json", trade_rows("155960"))
    write_json(root / "raw/krx/ksq_bydd_trd/2018/20181012.json", trade_rows())
    k = dart_body.KrxRows(root, days)
    o = dart_body.extract(RESUMED)
    assert dart_body.krx_check(o, "KOSDAQ", "155960", k)[0] == "CONSISTENT"
    write_json(root / "raw/krx/ksq_bydd_trd/2018/20181012.json", trade_rows("155960"))
    assert dart_body.krx_check(o, "KOSDAQ", "155960", k)[0] == "CONFLICT"
    assert dart_body.krx_check(o, None, "155960", k)[0] == "NO_LINK"


# --- document.xml 수집 ---------------------------------------------------------

def make_zip(name="x.xml", body=b"<P>ok</P>"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, body)
    return b.getvalue()


def fetcher(handler, max_calls=10):
    seen = []

    def t(url, headers, timeout):
        seen.append(url)
        return handler(url)
    return Fetcher(t, RetryPolicy(max_attempts=1, min_interval=0, backoff_base=0), max_calls,
                   sleep=lambda s: None, log=lambda m: None), seen


def test_document_ok_failed_and_no_retry(tmp_path, monkeypatch):
    monkeypatch.setenv(DART_KEY_ENV, FAKE_KEY)
    root = tmp_path / "data"

    def h(url):
        if "20190101000001" in url:
            return Response(200, make_zip())
        return Response(200, b"<result><status>014</status><message>x</message></result>")
    f, seen = fetcher(h)
    st = dart_document.collect_documents(root, ["20190101000001", "20190101000002", "20230102000001"], f,
                                         log=lambda m: None)
    assert (st["ok"], st["failed"], st["skipped_after_cutoff"], st["calls"]) == (1, 1, 1, 2)
    assert (root / "raw/opendart_document/2019/20190101000001.zip").exists()
    led = Ledger(root / "raw/opendart_document/_ledger.jsonl")
    assert led.get("20190101000002")["api_status"] == "014"
    text = (root / "raw/opendart_document/_ledger.jsonl").read_text(encoding="utf-8")
    assert FAKE_KEY not in text and "crtfc_key" not in text and "http" not in text.replace("http_status", "")
    f2, seen2 = fetcher(h)  # 성공·실패 모두 다시 요청하지 않는다
    st2 = dart_document.collect_documents(root, ["20190101000001", "20190101000002"], f2, log=lambda m: None)
    assert (st2["skipped_done"], st2["skipped_failed_before"], st2["calls"]) == (1, 1, 0) and not seen2


def test_document_key_echo_and_stop_status(tmp_path, monkeypatch):
    monkeypatch.setenv(DART_KEY_ENV, FAKE_KEY)
    root = tmp_path / "data"
    f, _ = fetcher(lambda url: Response(200, f"error {FAKE_KEY}".encode()))
    st = dart_document.collect_documents(root, ["20190101000001", "20190101000002"], f, log=lambda m: None)
    assert st["stopped"] and st["calls"] == 1
    assert not (root / "raw/opendart_document/_ledger.jsonl").exists()
    f, _ = fetcher(lambda url: Response(200, b"<result><status>020</status></result>"))
    st = dart_document.collect_documents(root, ["20190101000003", "20190101000004"], f, log=lambda m: None)
    assert st["stopped"] and st["calls"] == 1


# --- KIND ---------------------------------------------------------------------

def kind_html(rows):
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    head = "<tr>" + "".join(f"<th>{c}</th>" for c in kind.HEADER) + "</tr>"
    return f'<html><head><meta charset="EUC-KR"></head><body><table>{head}{tr}</table></body></html>'.encode("cp949")


def test_kind_parse_link_and_completeness(tmp_path):
    root = tmp_path / "data"
    days = [dt.date(2019, 1, 2), dt.date(2019, 1, 3), dt.date(2019, 1, 4)]
    write_json(root / "raw/krx/stk_isu_base_info/2019/20190102.json", master_rows("000001", "000002"))
    write_json(root / "raw/krx/stk_isu_base_info/2019/20190103.json", master_rows("000002"))
    write_json(root / "raw/krx/stk_isu_base_info/2019/20190104.json", master_rows("000002"))
    for d in days:
        write_json(root / f"raw/krx/ksq_isu_base_info/2019/{d:%Y%m%d}.json", master_rows("100001"))
    rows = kind.parse_kind_html(kind_html([["1", "회사A(현재명)", "000001", "2019-01-03", "해산 사유 발생", ""]]))
    assert rows[0] == kind.HEADER and rows[1][2] == "000001"
    seen = kind.master_presence(root, days)
    linked = kind.link({"KOSPI": rows[1:], "KOSDAQ": []}, seen, days)
    assert linked[0]["link"] == "LAST_SEEN=PREV_SESSION" and linked[0]["type"] == "EXIT"
    assert linked[0]["isin_krx"] == "KR7000001000" and linked[0]["krx_name_last"] == "N000001"
    gap = kind.unexplained_exits(seen, linked, days[-1])
    assert gap["in_kind"] == 1 and not gap["unexplained_common"]
    gap = kind.unexplained_exits(seen, [], days[-1])
    assert [g[0] for g in gap["unexplained_common"]] == ["000001"]
    with pytest.raises(ValueError):
        kind.parse_kind_html("<table><tr><td>x</td></tr></table>".encode("cp949"))
    t = kind.link({"KOSDAQ": [["1", "X", "100001", "2019-01-05", "유가증권시장 상장", ""]]}, seen, days)
    assert t[0]["type"] == "MARKET_TRANSFER"


# --- 월별 내보내기 ---------------------------------------------------------------

def test_export_krx_month_and_refuse_overwrite(tmp_path, monkeypatch):
    from test_collect import FakeTransport, default_handler, make_fetcher
    monkeypatch.setenv(krx.KEY_ENV, "FAKEKEY0123456789abcdefFAKEKEY0123456789")
    layout = krx.Layout(tmp_path / "data")
    d = dt.date(2019, 1, 2)
    krx.collect(layout, d, d, make_fetcher(FakeTransport(default_handler)), log=lambda m: None)
    res = export.export_krx_month(layout.data_root, "201901", tmp_path / "out")
    dest = tmp_path / "out" / "kr6_krx_201901"
    assert res["ledger_records"] == 4 and not handoff.verify_sha256sums(dest)
    assert json.loads((dest / "verify.json").read_text())["complete"] == 4
    with pytest.raises(FileExistsError):
        export.export_krx_month(layout.data_root, "201901", tmp_path / "out")
    assert export.month_window("202212")[1] == dt.date(2022, 12, 29)


# --- 이전(handoff) --------------------------------------------------------------

def make_tar(path, files, extra=None):
    with tarfile.open(path, "w:gz") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        for ti in extra or []:
            tf.addfile(ti)


def month_tar(path, payload=b"{}", sums_ok=True):
    import hashlib
    rel = "raw_krx/stk_bydd_trd/2019/20190102.json"
    sha = hashlib.sha256(payload if sums_ok else b"other").hexdigest()
    make_tar(path, {f"kr6_krx_201901/{rel}": payload, "kr6_krx_201901/SHA256SUMS": f"{sha}  ./{rel}\n".encode()})


def test_safe_extract_rejects_traversal_and_links(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    make_tar(bad, {"kr6_krx_201901/../../evil": b"x"})
    with pytest.raises(handoff.UnsafeArchive):
        handoff.safe_extract(bad, tmp_path / "s1")
    link = tarfile.TarInfo("kr6_krx_201901/raw_krx/x")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    make_tar(bad, {}, [link])
    with pytest.raises(handoff.UnsafeArchive):
        handoff.safe_extract(bad, tmp_path / "s2")
    make_tar(bad, {"/abs/file": b"x"})
    with pytest.raises(handoff.UnsafeArchive):
        handoff.safe_extract(bad, tmp_path / "s3")


def test_restore_dry_run_apply_identical_and_conflict(tmp_path):
    bundle, root = tmp_path / "bundle", tmp_path / "data"
    bundle.mkdir()
    month_tar(bundle / "kr6_krx_201901.tar.gz", b'{"a":1}')
    r = handoff.restore(bundle, root, apply=False)
    assert r["archives"]["kr6_krx_201901.tar.gz"]["new"] == 1 and not root.exists()
    r = handoff.restore(bundle, root, apply=True)
    target = root / "raw/krx/stk_bydd_trd/2019/20190102.json"
    assert target.read_bytes() == b'{"a":1}'
    r = handoff.restore(bundle, root, apply=True)
    assert r["archives"]["kr6_krx_201901.tar.gz"]["identical"] == 1 and not r["conflict"]
    target.write_bytes(b"local edit")
    r = handoff.restore(bundle, root, apply=True)
    assert r["conflict"] and target.read_bytes() == b"local edit"  # 덮어쓰지 않는다


def test_restore_rejects_bad_internal_checksum_and_symlinked_target(tmp_path):
    bundle, root = tmp_path / "bundle", tmp_path / "data"
    bundle.mkdir()
    month_tar(bundle / "kr6_krx_201901.tar.gz", b"{}", sums_ok=False)
    r = handoff.restore(bundle, root, apply=True)
    assert "kr6_krx_201901.tar.gz" in r["rejected"] and not root.exists()
    month_tar(bundle / "kr6_krx_201901.tar.gz", b"{}")
    (root / "raw").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "raw" / "krx").symlink_to(outside)
    r = handoff.restore(bundle, root, apply=True)
    assert "kr6_krx_201901.tar.gz" in r["rejected"] and not list(outside.iterdir())


def test_check_manifest(tmp_path):
    import hashlib
    (tmp_path / "a.bin").write_bytes(b"abc")
    m = tmp_path / "M.tsv"
    m.write_text("# c\nrelpath\tsize\tsha256\n"
                 f"a.bin\t3\t{hashlib.sha256(b'abc').hexdigest()}\nmissing.bin\t1\t00\n", encoding="utf-8")
    r = handoff.check_manifest(tmp_path, m)
    assert r["ok"] == 1 and r["missing"] == ["missing.bin"] and not r["bad"]
