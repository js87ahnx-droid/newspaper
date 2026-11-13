"""아침 발행을 뉴욕 장 마감 뒤로 (S46, 2026-11-13 "13일 호에 하루 전 장 마감 기사").

호 D 의 직전 뉴욕 거래일(D-1, 뉴욕 날짜)이 장을 연 날이면, 그날 마감(16:00 뉴욕) + 30분 전에는 발행하지 않는다.
겨울(뉴욕 표준시)엔 06:30 KST, 여름엔 05:30 KST — 마감 기사는 장 끝나고 0~30분 사이에 나온다 (11/11~11/13 실측).
D-1 이 주말·휴장일이면 기다리지 않는다. 기준은 오늘 날짜가 아니라 호 날짜 (놓친 호를 새벽에 다시 만들 때 막지 않게).

사용: python3 scripts/ny_close_wait.py <호 날짜 YYYY-MM-DD>  → "wait <마감+30분 KST>" 또는 "go" 를 찍는다.
NOW (ISO, 시간대 포함) 환경변수로 지금 시각을 바꿀 수 있다 (테스트). 표준 라이브러리만 쓴다 (check 작업은 pip 설치 없음).
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.market import MARKETS, SEOUL, _at, _trading  # noqa: E402

MARGIN = timedelta(minutes=30)


def ready_at(edition: date) -> datetime | None:
    """이 호를 발행해도 되는 가장 이른 시각. 기다릴 장이 없으면 None."""
    us = MARKETS["us"]
    ny_day = edition - timedelta(days=1)
    if not _trading(us, ny_day):
        return None
    return _at(us, ny_day, us.close) + MARGIN


def main(argv: list[str]) -> int:
    edition = date.fromisoformat(argv[1])
    now = datetime.fromisoformat(os.environ["NOW"]) if os.environ.get("NOW") else datetime.now(SEOUL)
    at = ready_at(edition)
    if at is not None and now < at:
        print(f"wait {at.astimezone(SEOUL):%H:%M}")
    else:
        print("go")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
