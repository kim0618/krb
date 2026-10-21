# KR-B 연구 규칙

작성일: 2026-10-21 (KR-B INDEPENDENT PROJECT BOOTSTRAP V1)

## 1. 단계와 Gate

| Phase | 이름 | 진입 Gate (사용자 승인 필요) |
|---|---|---|
| 0 | DATA FEASIBILITY | 없음 (현재 단계) |
| 1 | CENSUS | 대상 전략의 필수 데이터가 실데이터 표본으로 PASS, 이용조건 확인 |
| 2 | CONTRACT FREEZE | Census 결과 승인. 가설·변수·비용·평가지표를 결과 보기 전에 고정 |
| 3 | BACKTEST | 계약 동결본 승인 |
| 4 | HOLDOUT | 백테스트 판정 승인. Holdout 구간은 Phase 2에서 미리 지정 |
| 5 | PAPER CONTRACT | Holdout PASS |
| 6 | PAPER | Paper 계약 승인 |
| 7 | LIVE AUTO | Paper 판정 승인 + LIVE 주문 별도 승인 |

현재 판정:

```text
KR_AUTO_DATA_PREVALIDATION_V1 = PARTIAL
FIRST_RESEARCH_CANDIDATE      = UNDECIDED
PHASE_0_COMPLETE              = NO
```

## 2. 등록된 연구 대상

아래 4개만 연구한다. 새 전략을 추가하지 않는다. **어떤 전략도 PASS가 아니다.**
정의 출처: US-B KR EQUITY PHASE 0 V1 지시서 1절(2026-10-21).
"구성 요소"는 원문 그대로이고, "연구 질문" 문장은 원문 구성 요소를 한 문장으로 옮긴 것이다(새 조건 추가 없음).

### KR-1: KR-ACCUMULATION-SURGE

연구 질문: 가격 압축 + 거래대금 지속 + 투자자별 누적 순매수가 나타난 종목에서, 이후 급등 확률이 높아지는가?

- 구성 요소: 가격 압축, 거래대금 지속, 투자자별 누적 순매수, 이후 급등 확률
- 데이터 조건: **종목별** 투자자별 수급(시장 합산으로는 불충족), 2019년~, 상폐 포함
- 의존 Phase 0 항목: P0-1, P0-3, P0-4

### KR-2: KR-CONTRACT-EVENT

연구 질문: 공공조달 낙찰·계약 사건이 DART 공시보다 먼저 공개될 때 정보차가 있고, 계약 규모에 따라 가격이 반응하는가?

- 구성 요소: 공공조달 낙찰/계약, DART 공시 전후 정보차, 상장회사 매핑, 계약 규모와 가격 반응
- 데이터 조건: 조달 사건의 최초 공개시각 재현, 사업자 → 법인 → DART corp_code → 종목 매핑
- 의존 Phase 0 항목: P0-2, P0-3

### KR-3: KR-TURNAROUND-BREAKOUT

연구 질문: 펀더멘털 개선 후 중기 조정을 거친 종목이 추세를 회복할 때, 수급과 거래대금이 동반되면 초과수익이 있는가?

- 구성 요소: 펀더멘털 개선, 중기 조정, 추세 회복, 수급 및 거래대금
- 데이터 조건: PIT 재무(공시 접수일 기준), 수급, 상폐 포함 Universe
- 의존 Phase 0 항목: P0-1, P0-2(DART 재무), P0-3

### Overlay: KR-SECTOR-ROTATION

독립 전략이 아니다. 위 전략의 후속 Overlay로만 다룬다.

## 3. 첫 연구 후보 결정 규칙 (V1 지시서 13절 그대로)

1. P0-1의 역사적 수급·Universe·PIT·이용조건이 충분히 검증되면 → `KR-ACCUMULATION-SURGE`
2. P0-1이 불가능하거나 부분 충족이고 P0-2가 검증되면 → `KR-CONTRACT-EVENT`
3. 어느 쪽도 충분하지 않으면 → `UNDECIDED`, Census를 시작하지 않는다.

## 4. 판정 용어

| 판정 | 의미 |
|---|---|
| PASS | 실제 접근 가능한 공식 데이터와 필요 필드·기간·이용조건이 충분히 입증됨 |
| PARTIAL | 일부 확인, 핵심 기간·PIT·상폐·권한 중 미완료 있음 |
| FAIL | 공식적으로 불가능하거나 필수 조건 미충족이 입증됨 |
| UNKNOWN | 공식 근거 부족, 또는 인증·계약 문제로 확인 못 함 |

공식 문서 확인을 실데이터 호출 검증으로 취급하지 않는다.

## 5. 전략 원칙

- 결과를 보고 기존 전략을 수정하지 않는다. FAIL RESCUE 금지. V1 FAIL이면 V1 CLOSED.
- 새 가설은 V2로 사전등록.
- 과거 표본에 맞춘 과최적화 금지. Threshold 탐색은 계약 동결 범위 안에서만.
- 비용은 백테스트 전에 확정.
- 연구 결과(엣지가 있는가)와 운영 가능성(주문 경로·비용·용량)을 따로 판정.
