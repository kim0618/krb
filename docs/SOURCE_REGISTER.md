# 데이터 소스 등록부

작성일: 2026-10-21. 근거: [P0_V1_REVIEW.md](P0_V1_REVIEW.md)(V1 문서 조사, 2026-10-21 확인).

## 표기

| 표기 | 의미 |
|---|---|
| **[문서]** | 공식 문서·공개 화면에서 확인. 실데이터 호출 검증은 아님 |
| **[관찰]** | V1 조사 중 공개 화면을 1회 이상 직접 조회해 확인 |
| **[추정]** | 정황·비공식 자료 기반. 사실로 쓰지 않는다 |
| **UNKNOWN** | 근거 없음 |

**모든 소스의 실데이터 검증 = 0건.** 판정은 전부 문서 기준이다.

## 요약

| # | 소스 | 주 용도 | 판정 | 실데이터 검증 | 다음 검증 |
|---|---|---|---|---|---|
| 1 | KRX Open API | Universe, OHLCV | PARTIAL | 없음 | S1 |
| 2 | KRX Data Marketplace(유료 상품) | 과거 종목별 수급 | UNKNOWN | 없음 | S3 |
| 3 | KRX 정보데이터시스템 | 종목별 수급(화면) | FAIL(자동 수집 경로로서) | 없음 | 없음(사용 금지) |
| 4 | 키움 국내주식 REST API | 종목별 수급 | PARTIAL | 없음 | S2 |
| 5 | KIS Open API | 종목별 수급, 주문 | PARTIAL | 없음 | S2 |
| 6 | 조달청 나라장터 API | 계약·낙찰 | PARTIAL | 없음 | S4 |
| 7 | OpenDART | 공시, 기업 매핑, 재무 | PARTIAL | 없음 | S5 |
| 8 | KIND | 상폐·위험종목·공시시각 | PARTIAL | 없음 | S6 |

3번의 FAIL은 "데이터가 없다"가 아니라 "약관상 자동 수집 경로로 쓸 수 없다"는 뜻이다.

---

## 1. KRX Open API

| 항목 | 내용 |
|---|---|
| 공식 URL | 서비스 목록 https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd / 약관 https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO002.jsp |
| 데이터 종류 | 일별매매정보, 종목기본정보(ISU_CD, 단축코드, LIST_DD, 주식종류, 소속부, 상장주식수). ETF/ETN은 별도 서비스 [문서]. **종목별 투자자 수급 없음**(31개 서비스 중 0개) [문서] |
| 역사적 조회 범위 | 2010-01-04부터 basDd별 [문서] |
| 상장폐지 포함 | UNKNOWN. 과거 날짜 조회 시 이후 상폐 종목 포함 [추정] |
| PIT 재현 | 날짜별 스냅샷이라 가능성 높음 [추정]. 상폐 포함이 확인돼야 성립 |
| 인증 | 인증키(유효 1년) [문서] |
| 이용조건 | 비상업 목적만, 제3자 제공 금지 [문서]. **개인 자동매매가 "비상업"인지 UNKNOWN** |
| 자동수집 허용 | 키당 하루 1만 회 범위 [문서] |
| 원본 저장 | 계약 종료 후 이용 불가(약관 11조3항) [문서] |
| 비용 | 무료 [추정] |
| 호출 제한 | 하루 1만 회 [문서] |
| 약관 시행일 | 2025-12-26 [문서] |
| 판정 | PARTIAL |
| 남은 UNKNOWN | 과거 날짜 상폐 포함, 자동매매의 비상업 해당 여부, 계약 종료 후 보관 |

## 2. KRX Data Marketplace (유료 데이터 상품)

| 항목 | 내용 |
|---|---|
| 공식 URL | 상품 목록 https://data.krx.co.kr/contents/MDC/INFO/informationController/MDCINFO008.cmd / 구입안내 https://openapi.krx.co.kr/contents/OPP/DATA/OPPDATA001.jsp / 분배상품 https://openapi.krx.co.kr/contents/OPP/DATA/OPPDATA002.jsp / 판매 목록·가격(로그인 필요) https://data.krx.co.kr/contents/MDC/DATA/datasale/index.cmd?viewNm=MDCDATA003 [문서 2026-10-21, V2-B] |
| 데이터 종류 | 주식 상품군에 "투자자별 거래실적" 판매 상품 존재 [문서 V2-B]. **종목별 여부는 UNKNOWN**. 별도로 코스콤 경유 분배상품 "참조정보: 종목별투자자별(종가)"이 있으나 Forward 분배 계약용 [문서 V2-B] |
| 역사적 조회 범위 | UNKNOWN (상품 상세의 "제공기간"은 로그인 뒤) |
| 상장폐지 포함 | UNKNOWN |
| PIT 재현 | UNKNOWN |
| 인증 | KRX 회원 로그인 [문서]. 결제 후 "이용목적 심사" 통과해야 수령 [문서 V2-B] |
| 이용조건 | 별도 「마켓데이터 상품 구매 및 이용약관」 본문 미열람. 개인이 단순 참고 외 목적으로 시세 이용 시 "별도 계약 필요" 문구 [문서 V2-B, OPPDATA003] |
| 자동수집 허용 | 해당 없음. 구매 상품은 이메일·웹 다운로드 파일 전달 [문서 V2-B] |
| 원본 저장 | UNKNOWN(계약 종료 후 보관 가능 여부가 핵심 질문) |
| 비용 | UNKNOWN. 견적 전 수치를 쓰지 않는다 |
| 호출 제한 | 해당 없음 / UNKNOWN |
| 판정 | UNKNOWN (상품군 존재만 [문서]. 종목별·기간·상폐·가격·저장 모두 미확인) |
| 남은 UNKNOWN | 종목별 상품 여부, 제공기간, 가격, 개인 구매·자동매매 이용 허용, 상폐 포함, 계약 종료 후 보관, 정정 이력. 문의 문안은 P0_V2B_INVESTOR_FLOW_RESULTS.md 7.2 |

## 3. KRX 정보데이터시스템

| 항목 | 내용 |
|---|---|
| 공식 URL | 약관 https://data.krx.co.kr/contents/MDC/INFO/informationController/MDCINFO003.cmd |
| 데이터 종류 | [12009] 종목별 투자자 수급(`MDCSTAT02302/02303`), 기관 세부 7유형(금융투자·보험·투신·사모·은행·기타금융·연기금), 금액·수량 각각 [문서] |
| 역사적 조회 범위 | 2019년까지 가능 [추정], 직접 확인 안 함 |
| 상장폐지 포함 | 가능 [추정](pykrx가 상폐종목검색 경로 사용). 단축코드 재사용 위험 |
| PIT 재현 | UNKNOWN(정정 이력 UNKNOWN) |
| 인증 | 2026-02부터 로그인 필수 [문서·관찰: 익명 POST가 `LOGOUT` 응답] |
| 이용조건 | **약관 10조2항 자동 수집 금지**, 허락 없는 복제 금지 [문서] |
| 자동수집 허용 | **금지** |
| 원본 저장 | 허락 없이 복제 금지 |
| 비용 | 화면 열람 무료 |
| 호출 제한 | 단시간 연속 호출 시 403 [관찰] |
| 약관 시행일 | 2026-08-29(KRX 홈페이지 약관) [문서] |
| 판정 | FAIL(자동 수집 경로로서). 수동 열람 참고용만 |
| 남은 UNKNOWN | 화면의 KRX/NXT 집계 범위, 정정 이력 |

pykrx 등 비공식 wrapper는 이 시스템을 긁는 방식이므로 KR-B 데이터 경로로 쓰지 않는다.

## 4. 키움 국내주식 REST API

| 항목 | 내용 |
|---|---|
| 공식 URL | 포털 https://openapi.kiwoom.com (메인·API 가이드만 렌더됨, 이용안내·FAQ는 자동화 접근 시 오류 페이지) / 명세 https://github.com/Kiwoom-Securities/Kiwoom-REST-API @953e5db [문서 V2-B] |
| 데이터 종류 | `ka10059`: 기준일 `dt`부터 과거로 연속조회(`cont-yn`/`next-key`). 개인·외국인·기관계·금융투자·보험·투신·기타금융·은행·연기금등·사모펀드·국가·기타법인·내외국인. 금액(백만원)/수량(천주·1주)은 `amt_qty_tp`로 **호출 분리**. 거래소 구분은 종목코드 `_NX`(NXT)·`_AL`(SOR) [문서 V2-B] |
| 역사적 조회 범위 | **명세에 없음** → UNKNOWN (S2 실호출 필요). 페이지당 행 수도 명세 없음 |
| 상장폐지 포함 | UNKNOWN |
| PIT 재현 | UNKNOWN. 확정 시각 UNKNOWN |
| 인증 | 계좌 + 앱키 + 토큰 [문서] |
| 이용조건 | 예제 코드 재배포 금지 [문서]. 시세 저장·연구 이용 조건 UNKNOWN |
| 자동수집 허용 | UNKNOWN |
| 원본 저장 | UNKNOWN |
| 비용 | 무료 [추정] |
| 호출 제한 | 공식 예제가 0.2초 간격 [문서]. 오류코드 1700/1701/1702(요청 개수 초과)만 있고 수치 없음 [문서 V2-B] |
| 판정 | PARTIAL (실호출 0회, V2-B BLOCKED: KR-B 인증정보 없음) |
| 남은 UNKNOWN | 과거 깊이, 페이지당 행 수, 상폐 종목(오류코드 1901/1902로 거부될 가능성 [추정]), 모의 도메인 지원, 이용약관·저장 허용, 연기금 정의 차이 처리 |

US-B에 키움 인증 구현과 앱키가 있지만 **복사·import하지 않는다.** 같은 계정을 쓸지는 사용자가 정하고 KR-B 환경변수로 직접 주입한다.

## 5. KIS Open API (한국투자증권)

| 항목 | 내용 |
|---|---|
| 공식 URL | 포털 https://apiportal.koreainvestment.com/about-open-api / 공식 GitHub https://github.com/koreainvestment/open-trading-api (HEAD 2026-10-14) |
| 데이터 종류 | `FHPTJ04160001` 종목별 투자자 수급(증권·투신·사모·은행·보험·종금·기금 등, 금액·수량) [문서]. `FHKST01010900` 주식현재가 투자자 [문서]. 시장 구분 J/NX/UN [문서]. 주문·잔고·실시간 TR(P0_V1_REVIEW 6절) |
| 모의투자 | **`FHPTJ04160001` 모의투자 미지원** (포털 명시) [문서 V2-B]. S2는 실전 계좌 앱키 필요 |
| 상세 명세 (V2-B) | 기준일 `FID_INPUT_DATE_1`부터 `tr_cont`(M→N) 연속조회. 한 호출에 순매수·매수·매도의 수량(주)과 대금(백만원) 모두. 외국인 등록/비등록 분리, 기타법인·기타단체 별도. `FID_ETC_CLS_CODE`는 포털 "1" vs GitHub 공란으로 문서 불일치 [문서 V2-B] |
| 역사적 조회 범위 | **명세에 없음** → UNKNOWN (S2 실호출 필요). 페이지당 행 수도 명세 없음 |
| 상장폐지 포함 | UNKNOWN |
| PIT 재현 | 당일분은 15:40 이후 가집계, 산출 시각 일정하지 않을 수 있음 [문서 V2-B]. 정정 이력 필드 없음 |
| 인증 | 계좌 + 앱키, 토큰 24시간, 재발급 1분 1회 [문서] |
| 이용조건 | 개인이 본인 자산으로 매매 [문서]. 시세 제3자 제공은 제휴 필요 [문서] |
| 자동수집 허용 | 본인 투자 목적 범위 [추정] |
| 원본 저장 | UNKNOWN(영구 저장 허용 여부 문의 필요) |
| 비용 | 무료 [추정] |
| 호출 제한 | 초과 시 EGW00201 [문서]. 실전 초당 20회·모의 초당 2회 [추정, 공식 샘플 간격 기반] |
| 판정 | PARTIAL (실호출 0회, V2-B BLOCKED: KR-B 인증정보 없음) |
| 남은 UNKNOWN | 과거 깊이, 페이지당 행 수, 상폐 종목, 저장 허용, `FID_ETC_CLS_CODE` 올바른 값, 사용자 계좌 실동작 |

## 6. 조달청 나라장터 API (data.go.kr)

| 항목 | 내용 |
|---|---|
| 공식 URL | 낙찰 https://www.data.go.kr/data/15129397/openapi.do / 계약 https://www.data.go.kr/data/15129427/openapi.do / 사용자 https://www.data.go.kr/data/15129466/openapi.do / 개방표준 https://www.data.go.kr/data/15058815/openapi.do |
| 데이터 종류 | 계약(ChgHstry·DltHstry, rgstDt/chgDt 초 단위, corpList 사업자등록번호·지분율, cntrctOrd), 낙찰(낙찰자 사업자등록번호, 실개찰일시, 등록일시, 공고차수), 사용자(corprtRgstNo, 본사구분명) [문서] |
| 역사적 조회 범위 | 계약정보 페이지 표기 "2004-07 ~ 2025-01" [문서]. 2025-01 이후 실제 제공 여부 UNKNOWN. 개방표준은 조회기간 1주 단위 [문서] |
| 상장폐지 포함 | 해당 없음(조달업체 기준). 상폐사 매핑은 DART·KIND 쪽 문제 |
| PIT 재현 | **공개시각 필드 없음 [문서, CONFIRMED]**. rgstDt는 공개시각 대용 불가. 변경·삭제 이력으로 정정 추적은 가능 [문서] |
| 인증 | data.go.kr 서비스키(자동승인) [문서] |
| 이용조건 | 이용허락범위 제한 없음 [문서] |
| 자동수집 허용 | 금지 문구 없음 [문서] |
| 원본 저장 | 허용 [추정] |
| 비용 | 무료 [문서] |
| 호출 제한 | 개발계정 낙찰·계약 1,000회, 사용자·개방표준 10,000회 [문서]. 운영계정 한도 미기재 |
| 문서 수정일 | 낙찰정보 페이지 2026-10-02 [문서] |
| 판정 | PARTIAL |
| 남은 UNKNOWN | 2025-01 이후 데이터, 최초 공개시각 근거, 사업자번호 → 법인 → corp_code 적중률, 수의계약 공고번호 공백 연결 |

## 7. OpenDART

| 항목 | 내용 |
|---|---|
| 공식 URL | 기업개황 https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002 / 고유번호 https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019018 / 공시검색 https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001 |
| 데이터 종류 | corp_code, jurir_no, 기업개황(현재 값만), 공시 목록(list.json), 원문(document.xml), 재무 [문서]. 단일판매·공급계약은 구조화 API 없음 → I001 원문 파싱 |
| 역사적 조회 범위 | 공시 목록 장기 제공 [추정]. 정확한 시작 시점은 확인 필요 |
| 상장폐지 포함 | 고유번호 파일의 상폐사 포함 여부 UNKNOWN (S5) |
| PIT 재현 | **list.json은 접수일만, 시각 없음 [문서]**. 정정공시는 별도 공시로 존재 [추정]. 기업개황은 현재 값만이라 과거 상호는 공시로 재구성 |
| 인증 | API 키 [문서] |
| 이용조건 | 공공데이터라 이용 허용, 책임은 이용자, API 저작권 금감원 [문서] |
| 자동수집 허용 | 허용(한도 내) [문서] |
| 원본 저장 | 허용 [문서] |
| 비용 | 무료 [문서] |
| 호출 제한 | 개인 키 하루 2만 건, 분당 1,000회 이상이면 제한 가능 [문서] |
| 판정 | PARTIAL |
| 남은 UNKNOWN | 상폐사 corp_code, 접수 시각 확보 경로(KIND 3년 창 외), 정정공시 연결 규칙 |

## 8. KIND (한국거래소 기업공시채널)

| 항목 | 내용 |
|---|---|
| 공식 URL | 시장경보 https://kind.krx.co.kr/investwarn/investattentwarnrisky.do?method=investattentwarnriskyMain / 상장폐지 https://kind.krx.co.kr/investwarn/delcompany.do?method=searchDelCompanyMain / 관리종목 https://kind.krx.co.kr/investwarn/adminissue.do?method=searchAdminIssueList / 공시 상세검색 https://kind.krx.co.kr/disclosure/details.do |
| 데이터 종류 | 상장폐지(일자·사유, 엑셀), 시장경보(공시일·지정일·해제일), 관리종목·거래정지(현재 목록), 공시 분 단위 시각 [관찰] |
| 역사적 조회 범위 | 상장폐지 2000년~, 시장경보 2007년~ [관찰]. 상세검색 기간 3년 제한 [관찰] |
| 상장폐지 포함 | 상장폐지 이력 자체를 제공 [관찰]. 2019년 38건은 시장 구분 기본값 의심 |
| PIT 재현 | 시장경보 지정·해제일 있음 [관찰]. 관리종목·거래정지는 과거 이력 없음. 행 아이콘은 현재 상태(함정) |
| 인증 | 공개 화면 비로그인 [관찰] |
| 이용조건 | UNKNOWN |
| 자동수집 허용 | UNKNOWN (부하 민감). **약관 확인 전 자동 조회 금지** |
| 원본 저장 | UNKNOWN |
| 비용 | 무료(화면) |
| 호출 제한 | UNKNOWN |
| 판정 | PARTIAL |
| 남은 UNKNOWN | 이용약관, 단기과열 일괄 이력, 분할·병합·감자 필드, 관리종목·거래정지 과거 이력, 회사코드 → ISIN 매핑 |

---

## 참고 (등록 대상 외)

- 신한 indi: Windows ActiveX/COM만 근거, REST UNKNOWN. https://www.shinhansec.com/siw/customer-center/channel/channel_homeTrading-indi/contents.do
- LS증권 Open API: REST, 모의 있음, 2026-10-31부터 앱키당 세션 3개. https://openapi.ls-sec.co.kr/intro
- pykrx(비공식): KRX 정보데이터시스템 의존, 로그인 전환 이슈 #276 #278 #286. KR-B 경로로 쓰지 않음.

## 갱신 규칙

- 실호출 검증을 하면 해당 칸의 [문서]/[추정]을 [실측 YYYY-MM-DD]로 바꾸고 근거(호출 수, 표본, 결과 파일 경로)를 남긴다.
- 판정은 근거가 생길 때만 바꾼다. 추정으로 올리지 않는다.
