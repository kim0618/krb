# KR-B Agent Rules

이 파일은 KR-B 저장소에서 작업하는 코딩 에이전트가 반드시 따라야 하는 규칙이다.
KR-B는 독립 프로젝트이며 US-B(`/home/tjd618/usb`)의 하위 프로젝트가 아니다.
US-B의 AGENTS.md(America/New_York 캘린더, KST 하드코딩 금지 등)는 KR-B에 적용하지 않는다.

충돌 시 우선순위:

```text
현재 사용자 명시 지시
>
이 AGENTS.md
>
docs/RESEARCH_RULES.md
>
그 밖의 docs/
```

---

## 1. 프로젝트 정체성

- 대상: 대한민국 주식시장, KOSPI / KOSDAQ
- 거래소 캘린더: **XKRX**
- 타임존: **Asia/Seoul**
- 모든 시각은 timezone-aware로 다룬다. naive datetime을 저장하거나 비교하지 않는다.
- 거래일 판정은 XKRX 캘린더로 한다. 휴장일·장 운영시간을 코드에 하드코딩하지 않는다.
- 2025-03-04 이후 넥스트레이드(NXT) 거래가 있다. 데이터마다 KRX / NXT / 통합 범위를 명시한다.

## 2. US-B와의 경계

- `/home/tjd618/usb` 아래 파일을 수정·이동·삭제하지 않는다.
- US-B 패키지(`backend.app` 등)를 import하지 않는다. 필요한 기능은 KR-B 안에서 따로 구현한다.
- US-B의 DB, Collector, systemd 타이머, 운영 서버를 사용하지 않는다.
- US-B의 인증키·토큰·`.env`를 복사하지 않는다. KR-B 인증정보는 사용자가 환경변수로 직접 주입한다.
- US-B 문서는 읽기 전용 참고만 한다.

## 3. 연구 단계

| Phase | 이름 |
|---|---|
| 0 | DATA FEASIBILITY |
| 1 | CENSUS |
| 2 | CONTRACT FREEZE |
| 3 | BACKTEST |
| 4 | HOLDOUT |
| 5 | PAPER CONTRACT |
| 6 | PAPER |
| 7 | LIVE AUTO |

- 각 단계는 사용자가 승인한 Gate를 통과한 뒤에만 진행한다.
- 현재 단계: **Phase 0**. `PHASE_0_COMPLETE = NO`.
- Phase 0에서는 전략 구현, 백테스트, 수익률·신호 계산, Collector 개발·배포를 하지 않는다.

## 4. 데이터 원칙

- 데이터 확보가 전략 연구보다 우선한다.
- PIT(Point-in-Time) 재현을 검증한다. 오늘 기준 목록·값을 과거에 적용하지 않는다.
- Survivorship bias 금지. 상장폐지 종목 포함 여부를 소스마다 검증한다.
- Lookahead 금지. 사건 발생일과 정보 공개시각을 혼동하지 않는다.
- 원본 데이터(`data/raw/`)는 immutable. 덮어쓰지 않고, 정정은 새 버전으로 추가한다.
- 모든 레코드에 출처(source)를 기록한다.
- `available_at`(시장이 알 수 있게 된 시각)과 `retrieved_at`(우리가 받은 시각)을 구분해 저장한다.
- 데이터 정정 이력을 보존한다.
- 이용조건을 먼저 확인한다. 기술적으로 받을 수 있다는 것은 허락이 아니다.
- 공식 문서 확인과 실데이터 호출 검증을 구분해 기록한다.
- 데이터는 로컬에 저장한다. 운영 서버에 수집기를 배포하지 않는다.

## 5. 전략 원칙

- 결과를 보고 기존 전략을 수정하지 않는다.
- FAIL RESCUE 금지. V1이 FAIL이면 V1은 CLOSED.
- 새로운 가설은 V2로 사전등록한 뒤 검증한다.
- 과거 표본에 맞춘 과최적화 금지.
- 비용(수수료·세금·슬리피지)은 백테스트 전에 확정한다.
- 연구 결과와 운영 가능성을 분리해 판정한다.
- 연구 대상 전략은 `docs/RESEARCH_RULES.md`에 등록된 것만. 임의로 추가하지 않는다.

## 6. 개발 원칙

- 도구: **Claude Code ONLY**. Codex는 사용자가 다시 승인하기 전까지 금지.
- 모든 작업 프롬프트에 Claude 모델을 명시하고, 실제 사용 모델을 보고한다.
- 기본 브랜치 `main` 하나만 사용한다. 브랜치를 만들지 않는다.
- 다른 작업 세션의 dirty 파일을 보호한다.
- `git add .` / `git add -A` 금지. 파일을 지정해 stage한다.
- `git reset --hard`, `git clean`, `git stash`, 강제 push 금지.
- 임의 commit / push 금지. 커밋과 push는 사용자 지시가 있을 때만.
- 운영 배포 전 사용자 승인 필수.
- LIVE 주문 전 별도 승인 필수. 주문 API는 Phase 7 승인 전 호출하지 않는다.
- 실제 인증키·토큰·계좌번호·비밀번호를 추적 파일에 쓰지 않는다.
- 유료 API 결제, 대량 수집은 사용자 승인 없이 하지 않는다.

## 7. 저장소 구조

```text
AGENTS.md              이 규칙
README.md
pyproject.toml         독립 패키지 메타데이터
config/                *.example.toml만 추적, 실제 설정은 gitignore
docs/                  연구 규칙, 판정 문서, 소스 등록부, 검증 계획
src/krb/               KR-B 패키지
tests/                 KR-B 전용 테스트 (pytest, pythonpath=src)
data/raw|cache|processed/   전부 gitignore
reports/               판정 문서(.md)만 추적, 실행 산출물은 gitignore
```
