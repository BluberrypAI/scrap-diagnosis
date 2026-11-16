"""시각·날짜 규칙.

- 저장은 UTC(시간대 있는 datetime)로 한다.
- 사용자·경로추천 AI에게 내보낼 때는 Asia/Seoul(+09:00)로 바꾼다.
- 법 기준일(as_of)은 대화를 시작한 시각의 Asia/Seoul 날짜다.

한국은 1988년 이후 일광절약시간이 없으므로 고정 오프셋 +09:00을 쓴다
(Windows에는 tz 데이터베이스가 없어 zoneinfo에 tzdata 패키지가 필요해지는 것을 피한다).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_seoul(dt: datetime) -> datetime:
    """시간대가 없으면 UTC로 보고 Asia/Seoul로 바꾼다."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(SEOUL)


def seoul_iso(dt: datetime | None) -> str | None:
    """ISO 8601(초 단위, +09:00)."""
    return None if dt is None else to_seoul(dt).isoformat(timespec="seconds")


def seoul_date(dt: datetime) -> date:
    """그 시각의 Asia/Seoul 달력 날짜."""
    return to_seoul(dt).date()


def seoul_today() -> date:
    return seoul_date(utcnow())
