"""KR-6 수집기 테스트. 외부 네트워크를 쓰지 않는다(가짜 transport)."""

import datetime as dt
import io
import json
from contextlib import redirect_stdout

import pytest

from krb.collect import aux_sources, krx, normalize
from krb.collect.__main__ import run
from krb.collect.core import (
    CutoffViolation,
    Fetcher,
    Ledger,
    MissingCredential,
    Response,
    RetryPolicy,
    check_window,
    sha256_file,
)

FAKE_KEY = "FAKEKEY0123456789abcdefFAKEKEY0123456789"
D = dt.date(2019, 1, 2)


def trade_body(day, codes=("005930", "000660"), vol="100"):
    rows = [{"BAS_DD": f"{day:%Y%m%d}", "ISU_CD": c, "ISU_NM": f"N{c}", "MKT_NM": "KOSPI", "SECT_TP_NM": "",
             "TDD_CLSPRC": "100", "CMPPREVDD_PRC": "0", "FLUC_RT": "0", "TDD_OPNPRC": "100", "TDD_HGPRC": "110",
             "TDD_LWPRC": "90", "ACC_TRDVOL": vol, "ACC_TRDVAL": "10000", "MKTCAP": "1", "LIST_SHRS": "1"}
            for c in codes]
    return json.dumps({"OutBlock_1": rows}).encode()


def master_body(codes=("005930", "000660")):
    rows = [{"ISU_CD": f"KR7{c}003", "ISU_SRT_CD": c, "ISU_NM": f"N{c}", "ISU_ABBRV": f"N{c}",
             "ISU_ENG_NM": "E", "LIST_DD": "19750611", "MKT_TP_NM": "KOSPI", "SECUGRP_NM": "주권",
             "SECT_TP_NM": "", "KIND_STKCERT_TP_NM": "보통주", "PARVAL": "100", "LIST_SHRS": "1"} for c in codes]
    return json.dumps({"OutBlock_1": rows}).encode()


class FakeTransport:
    """URL로 응답을 고른다. 받은 URL·헤더를 기록해 키 처리 검사에 쓴다."""

    def __init__(self, handler):
        self.handler = handler
        self.seen = []

    def __call__(self, url, headers, timeout):
        self.seen.append((url, dict(headers)))
        return self.handler(url, headers)


def default_handler(url, headers):
    day = dt.datetime.strptime(url.split("basDd=")[1][:8], "%Y%m%d").date()
    if day.weekday() >= 5:
        return Response(200, b'{"OutBlock_1": []}')
    if "bydd_trd" in url:
        return Response(200, trade_body(day))
    return Response(200, master_body())


def make_fetcher(transport, max_calls=1000, **policy):
    return Fetcher(transport, RetryPolicy(min_interval=0, backoff_base=0, **policy), max_calls,
                   sleep=lambda s: None, log=lambda m: None)


@pytest.fixture
def env_key(monkeypatch):
    monkeypatch.setenv(krx.KEY_ENV, FAKE_KEY)


@pytest.fixture
def layout(tmp_path):
    return krx.Layout(tmp_path / "data")


# --- 기간 상한 ---------------------------------------------------------------

def test_cutoff_blocks_after_research_cutoff():
    with pytest.raises(CutoffViolation):
        check_window(dt.date(2022, 12, 1), dt.date(2022, 12, 30))
    with pytest.raises(CutoffViolation):
        check_window(dt.date(2023, 1, 2), dt.date(2023, 1, 3))
    with pytest.raises(CutoffViolation):
        check_window(dt.date(2017, 7, 31), dt.date(2017, 8, 2))
    check_window(dt.date(2017, 8, 1), dt.date(2022, 12, 29))


def test_collect_refuses_2023_without_calling(layout, env_key):
    t = FakeTransport(default_handler)
    with pytest.raises(CutoffViolation):
        krx.collect(layout, dt.date(2022, 12, 28), dt.date(2023, 1, 3), make_fetcher(t), log=lambda m: None)
    assert t.seen == []


def test_cli_rejects_2023(tmp_path, capsys):
    rc = run(["--data-root", str(tmp_path), "plan", "--start", "2022-12-01", "--end", "2023-01-02"])
    assert rc == 3


def test_plan_counts_weekdays_times_apis():
    jobs = krx.plan(dt.date(2019, 1, 1), dt.date(2019, 1, 7), krx.APIS)
    assert len(jobs) == 5 * 4  # 1/1(화)~1/7(월) 평일 5일


# --- 정상 수집, 파싱, 저장 구조 ------------------------------------------------

def test_collect_ok_and_layout(layout, env_key):
    t = FakeTransport(default_handler)
    stats = krx.collect(layout, D, D, make_fetcher(t), log=lambda m: None)
    assert stats["ok"] == 4 and stats["failed"] == 0 and stats["calls"] == 4
    for api in krx.APIS:
        p = layout.raw_file(api, D)
        assert p.exists()
        rec = Ledger(layout.ledger).get(krx.ledger_key(api, D))
        assert rec["status"] == "OK" and rec["rows"] == 2 and rec["sha256"] == sha256_file(p)
        assert rec["retrieved_at"].endswith("+09:00")
    assert not list(layout.raw.rglob("*.part"))


def test_empty_response_is_recorded_as_empty(layout, env_key):
    t = FakeTransport(lambda u, h: Response(200, b'{"OutBlock_1": []}'))
    stats = krx.collect(layout, D, D, make_fetcher(t), apis=["stk_bydd_trd"], log=lambda m: None)
    assert stats["empty"] == 1
    assert Ledger(layout.ledger).get(krx.ledger_key("stk_bydd_trd", D))["status"] == "EMPTY"


def test_bas_dd_mismatch_is_failure(layout, env_key):
    t = FakeTransport(lambda u, h: Response(200, trade_body(dt.date(2019, 1, 3))))
    stats = krx.collect(layout, D, D, make_fetcher(t), apis=["stk_bydd_trd"], log=lambda m: None)
    assert stats["failed"] == 1
    assert not layout.raw_file("stk_bydd_trd", D).exists()


@pytest.mark.parametrize("resp", [Response(200, b"<html>err</html>"), Response(200, b'{"respCode":"x"}'),
                                  Response(404, b"nf")])
def test_error_responses_not_complete(layout, env_key, resp):
    t = FakeTransport(lambda u, h: resp)
    stats = krx.collect(layout, D, D, make_fetcher(t), apis=["stk_bydd_trd"], log=lambda m: None)
    assert stats["failed"] == 1
    assert not krx.is_complete(layout, Ledger(layout.ledger), "stk_bydd_trd", D)


# --- 재시도, 중단 ------------------------------------------------------------

def test_transient_errors_retry_limited(layout, env_key):
    calls = {"n": 0}

    def h(u, hd):
        calls["n"] += 1
        return Response(503, b"") if calls["n"] < 3 else Response(200, trade_body(D))
    stats = krx.collect(layout, D, D, make_fetcher(FakeTransport(h), max_attempts=3), apis=["stk_bydd_trd"],
                        log=lambda m: None)
    assert stats["ok"] == 1 and stats["calls"] == 3


def test_transient_errors_give_up(layout, env_key):
    t = FakeTransport(lambda u, h: Response(None, b"", "URLError"))
    stats = krx.collect(layout, D, D, make_fetcher(t, max_attempts=3), apis=["stk_bydd_trd"], log=lambda m: None)
    assert stats["failed"] == 1 and stats["calls"] == 3


@pytest.mark.parametrize("code", [401, 403, 429])
def test_auth_or_rate_limit_stops_immediately(layout, env_key, code):
    t = FakeTransport(lambda u, h: Response(code, b""))
    stats = krx.collect(layout, D, dt.date(2019, 1, 4), make_fetcher(t), log=lambda m: None)
    assert stats["stopped"] and stats["calls"] == 1


def test_max_calls_cap(layout, env_key):
    t = FakeTransport(default_handler)
    stats = krx.collect(layout, D, dt.date(2019, 1, 31), make_fetcher(t, max_calls=5), log=lambda m: None)
    assert stats["calls"] == 5 and stats["stopped"]


def test_min_interval_enforced():
    sleeps = []
    clock = iter([0.0, 0.1, 0.1, 0.2]).__next__
    f = Fetcher(FakeTransport(lambda u, h: Response(200, b"{}")), RetryPolicy(min_interval=0.5), 10,
                sleep=sleeps.append, clock=clock, log=lambda m: None)
    f.fetch("a", "u", {})
    f.fetch("b", "u", {})
    assert sleeps and abs(sleeps[0] - 0.4) < 1e-9


# --- 체크포인트, 중복 방지, 부분 파일 -----------------------------------------

def test_resume_skips_completed(layout, env_key):
    t = FakeTransport(default_handler)
    krx.collect(layout, D, dt.date(2019, 1, 4), make_fetcher(t, max_calls=6), log=lambda m: None)
    t2 = FakeTransport(default_handler)
    stats = krx.collect(layout, D, dt.date(2019, 1, 4), make_fetcher(t2), log=lambda m: None)
    assert stats["skipped_complete"] == 6 and stats["calls"] == 12 - 6
    t3 = FakeTransport(default_handler)
    stats = krx.collect(layout, D, dt.date(2019, 1, 4), make_fetcher(t3), log=lambda m: None)
    assert stats["calls"] == 0 and t3.seen == []


def test_partial_file_not_complete_and_refetched(layout, env_key):
    p = layout.raw_file("stk_bydd_trd", D)
    p.parent.mkdir(parents=True)
    (p.parent / (p.name + ".part")).write_bytes(b'{"OutBlock_1": [')
    assert not krx.is_complete(layout, Ledger(layout.ledger), "stk_bydd_trd", D)
    stats = krx.collect(layout, D, D, make_fetcher(FakeTransport(default_handler)), apis=["stk_bydd_trd"],
                        log=lambda m: None)
    assert stats["ok"] == 1
    assert krx.is_complete(layout, Ledger(layout.ledger), "stk_bydd_trd", D)


def test_corrupted_file_detected_and_quarantined(layout, env_key):
    krx.collect(layout, D, D, make_fetcher(FakeTransport(default_handler)), apis=["stk_bydd_trd"], log=lambda m: None)
    p = layout.raw_file("stk_bydd_trd", D)
    p.write_bytes(b"tampered")
    v = krx.verify(layout, D, D, ["stk_bydd_trd"])
    assert v["hash_mismatch"] == ["stk_bydd_trd:20190102"]
    stats = krx.collect(layout, D, D, make_fetcher(FakeTransport(default_handler)), apis=["stk_bydd_trd"],
                        log=lambda m: None)
    assert stats["orphans_moved"] == 1 and stats["ok"] == 1
    assert krx.verify(layout, D, D, ["stk_bydd_trd"])["complete"] == 1


def test_file_without_ledger_is_quarantined_not_trusted(layout, env_key):
    p = layout.raw_file("stk_bydd_trd", D)
    p.parent.mkdir(parents=True)
    p.write_bytes(trade_body(D))
    stats = krx.collect(layout, D, D, make_fetcher(FakeTransport(default_handler)), apis=["stk_bydd_trd"],
                        log=lambda m: None)
    assert stats["orphans_moved"] == 1 and stats["calls"] == 1


def test_truncated_ledger_line_ignored(layout, env_key):
    krx.collect(layout, D, D, make_fetcher(FakeTransport(default_handler)), apis=["stk_bydd_trd"], log=lambda m: None)
    with layout.ledger.open("a") as f:
        f.write('{"key": "stk_bydd_trd:20190103", "sta')
    led = Ledger(layout.ledger)
    assert led.get("stk_bydd_trd:20190102")["status"] == "OK"
    assert led.get("stk_bydd_trd:20190103") is None


# --- 인증정보 처리 -----------------------------------------------------------

def test_missing_env_key_stops_before_any_call(layout, monkeypatch):
    monkeypatch.delenv(krx.KEY_ENV, raising=False)
    t = FakeTransport(default_handler)
    with pytest.raises(MissingCredential):
        krx.collect(layout, D, D, make_fetcher(t), log=lambda m: None)
    assert t.seen == []


def test_cli_missing_key_exit_code(tmp_path, monkeypatch):
    monkeypatch.delenv(krx.KEY_ENV, raising=False)
    assert run(["--data-root", str(tmp_path), "krx", "--start", "2019-01-02", "--end", "2019-01-02"]) == 3


def test_key_sent_in_header_not_url(layout, env_key):
    t = FakeTransport(default_handler)
    krx.collect(layout, D, D, make_fetcher(t), log=lambda m: None)
    for url, headers in t.seen:
        assert FAKE_KEY not in url
        assert headers.get("AUTH_KEY") == FAKE_KEY


def test_network_secret_mode_sends_no_key(layout, monkeypatch):
    monkeypatch.delenv(krx.KEY_ENV, raising=False)
    t = FakeTransport(default_handler)
    krx.collect(layout, D, D, make_fetcher(t), network_secret=True, log=lambda m: None)
    assert all("AUTH_KEY" not in h for _, h in t.seen)


def test_key_and_url_never_written_or_logged(layout, env_key, tmp_path):
    logs = []
    t = FakeTransport(lambda u, h: Response(None, b"", "URLError"))
    f = Fetcher(t, RetryPolicy(min_interval=0, backoff_base=0), 10, sleep=lambda s: None, log=logs.append)
    buf = io.StringIO()
    with redirect_stdout(buf):
        krx.collect(layout, D, D, f, log=logs.append)
    text = buf.getvalue() + "\n".join(logs)
    for p in layout.data_root.rglob("*"):
        if p.is_file():
            text += p.read_text(encoding="utf-8", errors="replace")
    assert FAKE_KEY not in text
    assert "basDd=" not in text and "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd?" not in text


def test_key_echo_in_response_stops_and_is_not_saved(layout, env_key):
    t = FakeTransport(lambda u, h: Response(200, json.dumps({"OutBlock_1": [], "echo": FAKE_KEY}).encode()))
    stats = krx.collect(layout, D, D, make_fetcher(t), log=lambda m: None)
    assert stats["stopped"]
    for p in layout.data_root.rglob("*"):
        if p.is_file():
            assert FAKE_KEY not in p.read_text(encoding="utf-8", errors="replace")


# --- 정규화, 품질 -------------------------------------------------------------

def test_normalize_preserves_fields_and_adds_meta(layout, env_key):
    krx.collect(layout, D, D, make_fetcher(FakeTransport(default_handler)), log=lambda m: None)
    r = normalize.normalize(layout, [D])
    assert r["written"] == 4
    text = layout.processed_file("stk_isu_base_info", D).read_text(encoding="utf-8")
    header = text.splitlines()[0].split(",")
    assert header[:3] == ["ISU_CD", "ISU_SRT_CD", "ISU_NM"] and "krb_raw_sha256" in header
    assert "KR7005930003" in text


def test_quality_join_and_vol0(layout, env_key):
    def h(u, hd):
        if "stk_bydd_trd" in u:
            return Response(200, trade_body(D, codes=("005930", "000660", "999999"), vol="0"))
        if "stk_isu_base_info" in u:
            return Response(200, master_body(codes=("005930", "000660", "123456")))
        return Response(200, b'{"OutBlock_1": []}')
    krx.collect(layout, D, D, make_fetcher(FakeTransport(h)), log=lambda m: None)
    q = normalize.quality(layout, [D])["KOSPI"]
    assert q["joined"] == 2 and q["unjoined"] == 1 and q["master_without_trade"] == 1
    assert q["vol0_rows"] == 3  # 거래량 0은 세기만 하고 정지로 분류하지 않는다


# --- 보조 원천 ---------------------------------------------------------------

def test_dart_i003_uses_detail_only_and_paginates(tmp_path, monkeypatch):
    monkeypatch.setenv(aux_sources.DART_KEY_ENV, FAKE_KEY)

    def h(u, hd):
        page = int(u.split("page_no=")[1].split("&")[0])
        assert "pblntf_detail_ty=I003" in u and "pblntf_ty=" not in u
        return Response(200, json.dumps({"status": "000", "total_page": 2, "total_count": 150,
                                         "list": [{"report_nm": "주권매매거래정지", "rcept_dt": "20190110"}] * (100 if page == 1 else 50)}).encode())
    t = FakeTransport(h)
    s = aux_sources.collect_dart_i003(tmp_path, dt.date(2019, 1, 1), dt.date(2019, 1, 31), make_fetcher(t),
                                      log=lambda m: None)
    assert s["pages_ok"] == 2 and s["calls"] == 2
    s2 = aux_sources.collect_dart_i003(tmp_path, dt.date(2019, 1, 1), dt.date(2019, 1, 31),
                                       make_fetcher(FakeTransport(h)), log=lambda m: None)
    assert s2["skipped"] == 2 and s2["calls"] == 0
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert FAKE_KEY not in p.read_text(encoding="utf-8", errors="replace")


def test_dart_limit_status_stops(tmp_path, monkeypatch):
    monkeypatch.setenv(aux_sources.DART_KEY_ENV, FAKE_KEY)
    t = FakeTransport(lambda u, h: Response(200, b'{"status":"020","message":"limit"}'))
    s = aux_sources.collect_dart_i003(tmp_path, dt.date(2019, 1, 1), dt.date(2019, 3, 31), make_fetcher(t),
                                      log=lambda m: None)
    assert s["stopped"] and s["calls"] == 1


def test_dart_window_is_monthly_and_capped():
    w = aux_sources.month_windows(dt.date(2022, 11, 15), dt.date(2022, 12, 29))
    assert w == [(dt.date(2022, 11, 15), dt.date(2022, 11, 30)), (dt.date(2022, 12, 1), dt.date(2022, 12, 29))]
    with pytest.raises(CutoffViolation):
        aux_sources.collect_dart_i003(__import__("pathlib").Path("/nonexistent"), dt.date(2022, 12, 1),
                                      dt.date(2023, 1, 5), make_fetcher(FakeTransport(default_handler)))


def test_fsc_rights_paging_empty_and_xml_error(tmp_path, monkeypatch):
    monkeypatch.setenv(aux_sources.DATAGOKR_KEY_ENV, FAKE_KEY)

    def h(u, hd):
        if "basDt=20190102" in u:
            return Response(200, json.dumps({"response": {"header": {"resultCode": "00"},
                                                          "body": {"totalCount": 3, "items": {"item": [{}, {}, {}]}}}}).encode())
        return Response(200, json.dumps({"response": {"header": {"resultCode": "00"},
                                                      "body": {"totalCount": 0, "items": ""}}}).encode())
    s = aux_sources.collect_fsc_rights(tmp_path, dt.date(2019, 1, 2), dt.date(2019, 1, 3), make_fetcher(FakeTransport(h)),
                                       log=lambda m: None)
    assert s["pages_ok"] == 1 and s["pages_empty"] == 1
    xml = b"<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    s = aux_sources.collect_fsc_rights(tmp_path, dt.date(2019, 1, 4), dt.date(2019, 1, 4),
                                       make_fetcher(FakeTransport(lambda u, h: Response(200, xml))), log=lambda m: None)
    assert s["stopped"]


def test_aux_missing_key_stops(tmp_path, monkeypatch):
    monkeypatch.delenv(aux_sources.DART_KEY_ENV, raising=False)
    t = FakeTransport(default_handler)
    with pytest.raises(MissingCredential):
        aux_sources.collect_dart_i003(tmp_path, dt.date(2019, 1, 1), dt.date(2019, 1, 2), make_fetcher(t))
    assert t.seen == []
