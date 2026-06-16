from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def taipei_now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def taipei_today():
    return taipei_now().date()


def taipei_date_string(fmt: str = "%Y-%m-%d") -> str:
    return taipei_now().strftime(fmt)


def utc_now_string(fmt: str = "%Y-%m-%dT%H:%M:%SZ") -> str:
    return datetime.now(timezone.utc).strftime(fmt)
