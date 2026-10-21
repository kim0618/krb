# KR-B

대한민국 주식시장(KOSPI / KOSDAQ)을 대상으로 하는 독립 정량 연구 프로젝트.

- 캘린더: XKRX / 타임존: Asia/Seoul
- 현재 단계: **Phase 0 DATA FEASIBILITY** (`PHASE_0_COMPLETE = NO`)
- 어떤 전략도 아직 PASS가 아니다.

US-B(`/home/tjd618/usb`)와는 별개 저장소다. US-B 코드·DB·인증정보를 쓰지 않는다.

## 문서

| 문서 | 내용 |
|---|---|
| [AGENTS.md](AGENTS.md) | 에이전트 작업 규칙 |
| [docs/RESEARCH_RULES.md](docs/RESEARCH_RULES.md) | 연구 단계, Gate, 등록 전략과 연구 질문 |
| [docs/P0_V1_REVIEW.md](docs/P0_V1_REVIEW.md) | Phase 0 V1 문서 조사 결과 이관 |
| [docs/SOURCE_REGISTER.md](docs/SOURCE_REGISTER.md) | 데이터 소스 등록부 |
| [docs/P0_V2_SAMPLE_PLAN.md](docs/P0_V2_SAMPLE_PLAN.md) | 다음 실데이터 표본 검증 계획 |

## 설정과 인증정보

`config/sources.example.toml`을 `config/sources.toml`로 복사해 쓴다(gitignore).
인증정보는 환경변수로만 주입한다. 변수 이름은 예제 파일에 있다.

## 테스트

```bash
python -m pytest
```

현재 테스트는 없다. 의존성 설치는 아직 하지 않았다.
