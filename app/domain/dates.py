"""Daty kalendarzowe bez strefy czasowej (YYYY-MM-DD).

Terminy liczymy według zasad prawa cywilnego (art. 111–112 KC), jak zaleca poradnik KPRM.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_STRICT = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MONTHS_GENITIVE = (
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
)


def _parts(value: str) -> tuple[int, int, int]:
    m = _ISO.match(value or "")
    if not m:
        raise ValueError(f'Nieprawidłowa data ISO: "{value}"')
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _to_date(value: str) -> date:
    y, m, d = _parts(value)
    return date(y, m, d)


def is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or not _STRICT.match(value):
        return False
    y, m, d = _parts(value)
    return 1 <= m <= 12 and 1 <= d <= calendar.monthrange(y, m)[1]


def to_iso_date(value: str) -> str:
    y, m, d = _parts(value)
    return f"{y:04d}-{m:02d}-{d:02d}"


def add_days(value: str, days: int) -> str:
    return (_to_date(value) + timedelta(days=days)).isoformat()


def add_months(value: str, months: int) -> str:
    """Art. 112 KC: koniec w dniu odpowiadającym datą, a gdy takiego nie ma — w ostatnim dniu miesiąca."""
    y, m, d = _parts(value)
    index = y * 12 + (m - 1) + months
    ty, tm = divmod(index, 12)
    tm += 1
    return f"{ty:04d}-{tm:02d}-{min(d, calendar.monthrange(ty, tm)[1]):02d}"


def diff_in_days(to: str, from_: str) -> int:
    return (_to_date(to) - _to_date(from_)).days


def days_inclusive(from_: str, to: str) -> int:
    return diff_in_days(to, from_) + 1


def compare(a: str, b: str) -> int:
    return diff_in_days(a, b)


def is_before(a: str, b: str) -> bool:
    return compare(a, b) < 0


def is_after(a: str, b: str) -> bool:
    return compare(a, b) > 0


def format_pl(value: str | None) -> str:
    if not value:
        return "—"
    y, m, d = _parts(value)
    return f"{d:02d}.{m:02d}.{y}"


def format_long_pl(value: str | None) -> str:
    if not value:
        return "—"
    y, m, d = _parts(value)
    return f"{d} {MONTHS_GENITIVE[m - 1]} {y}"


def plural_pl(count: int, forms: tuple[str, str, str]) -> str:
    n = abs(count)
    if n == 1:
        return forms[0]
    last, last_two = n % 10, n % 100
    if 2 <= last <= 4 and (last_two < 12 or last_two > 14):
        return forms[1]
    return forms[2]


def describe_due_in(due: str, today: str) -> str:
    days = diff_in_days(due, today)
    if days == 0:
        return "dziś"
    if days == 1:
        return "jutro"
    if days > 1:
        return f"za {days} {plural_pl(days, ('dzień', 'dni', 'dni'))}"
    overdue = abs(days)
    return f"{overdue} {plural_pl(overdue, ('dzień', 'dni', 'dni'))} po terminie"
