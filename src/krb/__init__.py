"""KR-B: 대한민국 주식시장(KOSPI/KOSDAQ) 독립 정량 연구 패키지.

현재 Phase 0(DATA FEASIBILITY). 전략 코드는 없다. `krb.collect`는 KR-6 과거 데이터의 로컬 수집기다(실행은 사용자 승인 뒤).
US-B 패키지를 import하지 않는다. 시각은 Asia/Seoul timezone-aware, 캘린더는 XKRX.
"""

__version__ = "0.0.0"

MARKET_TIMEZONE = "Asia/Seoul"
EXCHANGE_CALENDAR = "XKRX"
