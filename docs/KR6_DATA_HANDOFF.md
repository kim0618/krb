# KR-6 데이터 이전·재현 안내 (클라우드 → 로컬)

작성일: 2026-10-23 · 작성: Claude Code · 상태: 클라우드 수집 종료, 로컬 인계

이 문서는 클라우드 세션에서 확보한 KR-6 원본 데이터와 보조 자료를 로컬(WSL `/home/tjd618/krb`)에서
복원하고 이어서 작업하기 위한 안내다. **원본 데이터는 Git에 없다.** 데이터는 별도로 전달한 아카이브로만 옮긴다.
판정(Gate PASS 여부)의 정본은 계약 문서(`docs/KR6_DATA_CONTRACT_V0.md` 등)이며 이 문서는 계약을 바꾸지 않는다.

## 1. 현황

완료

| 항목 | 결과 |
|---|---|
| KRX OpenAPI 4개 API, 2017-08-01 ~ 2022-12-29 | 65/65개월, 요청 5,652건(OK 5,490 · EMPTY 162 · 실패 0), 시세 3,101,756행(KOSPI 1,217,399 · KOSDAQ 1,884,357), 고유 ISIN 2,749 |
| Gate D12 XKRX 거래일 | PASS. 1,332거래일, EMPTY 81일 = XKRX 평일 휴장 81일, `N_warm` 344 |
| D6(a) 정황 증거 | OHLC 이상 9행(시가·고가·저가 0, 거래량 > 0), Q5 거래대금 범위 위반 4,446/3,005,145행(0.148%) |
| OpenDART I003 목록 | 65개월 241페이지, 20,891건(분류는 제목 후보만) |
| OpenDART 공시 본문(document.xml) | 317요청 중 316건 ZIP(1건 status 014), 추출기 V2 결과 316행 |
| KIND 상장폐지현황(사용자 수동 다운로드) | 186건(KOSPI 34 · KOSDAQ 152, 시장 이전 7), 186/186 KRX 마스터 대조 일치 |

미완료

- 거래정지·해제 기간 복원: KOSDAQ 해제일 대부분이 조건부 문구("결정일까지")다. 남은 대상 본문 3,848건.
- KOSPI 장기 거래정지 원천: I003에 없음. KIND 공시 화면은 클라우드에서 차단(Akamai 403).
- 통상 정리매매 일정: I003 "정리매매" 분류 81건은 보류·재개만이다. 상장폐지 분류(1,061건) 본문 확인이 필요.
- D6(a) 공식 필드 범위: KRX OpenAPI 명세에 정규장·시간외 범위가 없다. KRX 문의 필요.
- 매직마이크로(127160) 정리매매 기간 충돌 1건(본문 '22.09.08~09.20, KRX 09-21 체결, KIND 폐지일 09-22). 미해결.
- 기업행위·SPAC 검증, 잔여 계약 Gate(D0~D11, D13), 백테스터 구현.

## 2. 데이터 배치 (`data/`, 전부 gitignore)

| 경로 | 내용 | 출처 | 전달 아카이브 |
|---|---|---|---|
| `raw/krx/<api>/<YYYY>/<YYYYMMDD>.json` | KRX 응답 원본(OutBlock_1) | KRX OpenAPI | `kr6_krx_<YYYYMM>.tar.gz` (2019-01은 `kr6_r1_krx_201901.tar.gz`) |
| `processed/krx/<api>/<YYYY>/<YYYYMMDD>.csv` | 정규화 CSV | 원본에서 생성 | 같음 |
| `raw/krx/_ledger.jsonl` | KRX 완료 장부(재개 기준) | 수집기 | `kr6_handoff_aux_20261023.tar.gz` |
| `raw/opendart_i003/<YYYY>/<YYYYMM>01_<YYYYMMDD>_ALL_p<NNNN>.json` | I003 목록 페이지 원본 | OpenDART list.json | `kr6_dart_i003_<YYYYMM>.tar.gz` |
| `processed/opendart_i003/<YYYY>/<YYYYMM>_classified.csv` | 분류·당시 KRX 연결 | `krb.collect.dart_i003` | 같음 |
| `raw/opendart_i003/_ledger.jsonl` | I003 완료 장부 | 수집기 | aux |
| `raw/opendart_document/<YYYY>/<rcept_no>.zip`, `_ledger.jsonl` | 공시 본문 원본 316건 + 장부 | OpenDART document.xml | aux |
| `processed/opendart_document/extract_v2.csv` | 본문 추출 V2 결과 | `krb.collect.dart_body` | aux |
| `processed/opendart_document/extract_v1_superseded.csv`, `targets_prioritized.csv` | V1 결과(감사용), 대상 우선순위 | 같음 | aux |
| `raw/kind_delist/20261023_user_upload/*.xls`, `20261023_user_upload.meta.json` | KIND 원본 2개(EUC-KR HTML 표) + 메타 | KIND, 사용자 수동 | aux |
| `processed/kind_delist/kind_delist_20170801_20221229_linked.csv` | KIND × KRX 연결 186행 | `krb.collect.kind` | aux |
| `processed/xkrx/XKRX_sessions_20170801_20221229.txt`, `d12_result.json` | D12 거래일 목록·결과 | exchange_calendars 4.13.2 | aux |
| `processed/d6a/d6a_ohlc_q5_evidence.txt` | D6(a) 증거 | `krb.collect.audit d6a` | aux |
| `processed/manifests/KR6_KRX_65M_MANIFEST.tsv`, `KR6_DART_I003_MANIFEST.tsv` | 월별 목록·SHA256 | 클라우드 점검 | aux |

전달 파일 전체의 상대 경로·크기·SHA256·출처·기간·유형은 함께 전달한 `KR6_HANDOFF_MANIFEST.tsv`(아카이브 단위)와
`KR6_HANDOFF_AUX_CONTENTS.tsv`(aux 안 파일 단위)에 있다. 월별 아카이브 안 파일은 각 아카이브의 `SHA256SUMS`가 덮는다.

이전에서 제외한 것: `data/raw/kr6_s2/`(S2 표본, HTTP 응답 헤더 파일 포함 — 민감 자료로 분류, 클라우드에도 권한 600으로만 보존),
세션 임시 작업 파일, 압축 해제 검사용 폴더, 가상환경. 인증키·쿠키·응답 헤더·전체 요청 URL은 어떤 전달 파일에도 없다.

## 3. 도구 (`src/krb/collect/`, 네트워크를 쓰는 것은 표시)

| 모듈 | 명령 | 하는 일 |
|---|---|---|
| `__main__` | `python -m krb.collect krx\|verify\|quality\|normalize\|plan\|dart-i003 ...` | 기존 수집기(네트워크: krx, dart-i003) |
| `dart_document` | `python -m krb.collect.dart_document --max-calls N <rcept_no>...` | **네트워크.** 공시 본문 ZIP. 장부에 있는 접수번호는 재요청하지 않음 |
| `dart_i003` | `python -m krb.collect.dart_i003 [--out-root DIR]` | I003 분류·당시 KRX 연결(현재 `corp_cls`로 거르지 않음) |
| `dart_body` | `python -m krb.collect.dart_body --targets T --out O` | 본문 추출 V2 + KRX 대조 |
| `kind` | `python -m krb.collect.kind --kospi F --kosdaq F --out O` | KIND 파싱·연결·완전성 점검 |
| `calendar_d12` | `python -m krb.collect.calendar_d12 build\|compare` | 거래일 목록 생성(`calendar` 추가 의존성)·대조 |
| `audit` | `python -m krb.collect.audit months\|d6a` | 65개월 점검, D6(a) 증거 |
| `export` | `python -m krb.collect.export krx\|dart --ym YYYYMM --out DIR` | 월별 전달 폴더(덮어쓰기 거부) |
| `handoff` | `python -m krb.collect.handoff check-manifest\|restore --bundle DIR [--apply]` | 전달 파일 검증·안전 복원 |

인증정보는 환경변수로만 넣는다: `KRB_KRX_OPENAPI_KEY`(또는 실행 환경 프록시 주입 시 `--network-secret`),
`KRB_OPENDART_API_KEY`, `KRB_DATAGOKR_SERVICE_KEY`. 복원·검증 명령은 키가 필요 없다.

## 4. 로컬 복원 절차 (WSL)

```bash
# 0) 저장소 최신화 — 로컬 변경이 있으면 멈추고 먼저 정리한다
cd /home/tjd618/krb                       # 없으면: git clone https://github.com/kim0618/krb.git /home/tjd618/krb
git status --short                        # 출력이 있으면 중단(다른 작업 보호)
git fetch origin main
git merge --ff-only origin/main           # fast-forward가 아니면 실패한다. 강제로 맞추지 않는다

# 1) 의존성과 테스트(외부 API 호출 없음)
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'                  # D12 목록을 다시 만들 때만 '.[test,calendar]'
python -m pytest -q

# 2) 전달 파일 배치: 내려받은 *.tar.gz 131개와 매니페스트 2개를 한 폴더에(이름은 매니페스트와 같아야 한다)
mkdir -p ~/krb_bundle                     # 저장소 밖
python -m krb.collect.handoff check-manifest --bundle ~/krb_bundle      # 크기·SHA256 전부 OK여야 한다

# 3) 복원: dry-run으로 충돌을 먼저 본다. 기존 파일은 SHA256이 같을 때만 건너뛰고, 다르면 CONFLICT(덮어쓰지 않음)
python -m krb.collect.handoff restore --bundle ~/krb_bundle             # rejected·conflict가 비어 있는지 확인
python -m krb.collect.handoff restore --bundle ~/krb_bundle --apply

# 4) 복원 검증
python -m krb.collect verify --start 2017-08-01 --end 2022-12-29        # complete 5652, mismatch·missing·part 0
python -m krb.collect.calendar_d12 compare                              # exit 0, sha256_matches_d12_record true
python -m krb.collect.audit months                                      # months_complete 65, trade_rows 3101756
python -m krb.collect.kind --kospi data/raw/kind_delist/20261023_user_upload/kind_delcompany_KOSPI_20170801_20221229.xls \
  --kosdaq data/raw/kind_delist/20261023_user_upload/kind_delcompany_KOSDAQ_20170801_20221229.xls \
  --out /tmp/kind_check.csv && cmp /tmp/kind_check.csv data/processed/kind_delist/kind_delist_20170801_20221229_linked.csv
python -m krb.collect.dart_i003 --out-root /tmp/i003_check >/dev/null && diff -rq /tmp/i003_check data/processed/opendart_i003
python -m krb.collect.dart_body --targets data/processed/opendart_document/targets_prioritized.csv --out /tmp/body_check.csv \
  && cmp /tmp/body_check.csv data/processed/opendart_document/extract_v2.csv
```

`restore`는 tar 멤버 중 절대경로·`..`·링크·장치 파일이 하나라도 있으면 그 아카이브 전체를 거부하고, 임시 폴더에
풀어 내부 `SHA256SUMS`를 모두 통과한 뒤에만 `data/`에 쓴다. 대상 경로에 심볼릭 링크가 있으면 거부한다.

## 5. 기대값 (복원 뒤 대조)

- `XKRX_sessions_20170801_20221229.txt` SHA256 `79720a5786313959cc0164c1ce2d6b390eca659f9832b57fe5f95a473b006817`
- KIND 원본: KOSPI `934fdf977b227e7180a762d03b8426632a1133de658ef531230122c319972ab9`,
  KOSDAQ `0bdd9b9021972fba8711c894386295121b06dbf19f60190779d4208b3c9cc355`
- 월별 KRX·I003 아카이브 SHA256: `processed/manifests/*.tsv`와 `KR6_HANDOFF_MANIFEST.tsv`

## 6. 이어서 할 때의 원칙

- 기존 원본·장부는 덮어쓰지 않는다. 정정은 새 파일·새 장부 줄로 추가한다(AGENTS.md 4절).
- KIND 상장폐지일은 완전성 점검용이며 당시 투자자가 알던 정보로 쓰지 않는다.
- 조건부 해제일을 날짜로 바꾸지 않는다. KRX 시세 재개일은 참고 증거로만 쓴다.
- 2022-12-29 이후 시장 데이터·공시는 Contract Freeze와 해제 절차 전에는 열지 않는다(계약 4.1).
