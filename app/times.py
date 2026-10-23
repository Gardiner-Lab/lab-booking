"""
Times: kept in UTC, read in the lab's own time zone.

Bookings are stored as UTC text ('2026-10-23T08:00:00Z'), which sorts and
compares correctly. Opening hours, steps and days are the lab's: TZ, or
Europe/Amsterdam.
"""

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def zone() -> ZoneInfo:
    try:
        return ZoneInfo((os.environ.get('TZ') or 'Europe/Amsterdam').lstrip(':'))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('Europe/Amsterdam')


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse(text) -> datetime:
    """An ISO time with its offset (or Z), as the browser sends it; a time without one is the lab's."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Give a time')
    try:
        value = datetime.fromisoformat(text.strip().replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'Not a time: {text}') from None
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone())
    return value.astimezone(timezone.utc).replace(microsecond=0)


def store(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime(FORMAT)


def load(text: str) -> datetime:
    return datetime.strptime(text, FORMAT).replace(tzinfo=timezone.utc)


def local(value: datetime) -> datetime:
    return value.astimezone(zone())


def minutes(hhmm: str) -> int:
    """'08:30' -> 510; '24:00' is the end of the day."""
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def clean_hhmm(text, default: str) -> str:
    text = (str(text or '').strip() or default)
    try:
        h, m = (int(x) for x in text.split(':'))
    except ValueError:
        raise ValueError(f'Give a time of day as HH:MM, not {text}') from None
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
        raise ValueError(f'Not a time of day: {text}')
    return f'{h:02d}:{m:02d}'


def at(day: date, mins: int) -> datetime:
    """The lab's day at so many minutes after midnight, in UTC (24:00 is the next midnight)."""
    base = datetime.combine(day, time(0), tzinfo=zone())
    if mins >= 24 * 60:
        base = datetime.combine(day + timedelta(days=1), time(0), tzinfo=zone())
        mins -= 24 * 60
    return (base + timedelta(minutes=mins)).astimezone(timezone.utc)


def day_bounds(day: date):
    """The lab's day, from midnight to midnight, in UTC."""
    return at(day, 0), at(day, 24 * 60)


def local_day(value: Optional[datetime] = None) -> date:
    return local(value or now()).date()
