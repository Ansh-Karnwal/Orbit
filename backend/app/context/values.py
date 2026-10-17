"""Strict boundary normalization shared by extraction, proposals and predicates."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo


def instant(value) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")
    return dt.astimezone(timezone.utc)


def iso(value) -> str:
    return instant(value).isoformat().replace("+00:00", "Z")


def cents(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise ValueError("Money must be integer cents, never a float")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid money") from exc
    if not number.is_finite() or number != number.to_integral_value() or number < 0:
        raise ValueError("Money must be nonnegative integer cents")
    return int(number)


def usd_to_cents(value: str) -> int:
    try:
        return cents(Decimal(value) * 100)
    except InvalidOperation as exc:
        raise ValueError("Invalid USD amount") from exc


def money(value: int) -> str:
    value = cents(value)
    return f"${value // 100}.{value % 100:02d}"


def normalize_slots(value) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("Slots must be a list")
    slots = set()
    for slot in value:
        start, end = instant(slot["start"]), instant(slot["end"])
        if start >= end:
            raise ValueError("Slot start must precede end")
        slots.add((iso(start), iso(end)))
    return [{"start": a, "end": b} for a, b in sorted(slots)]


def slot_pairs(value) -> set[tuple[datetime, datetime]]:
    try:
        return {(instant(s["start"]), instant(s["end"])) for s in normalize_slots(value)}
    except (ValueError, TypeError, KeyError):
        return set()


def local_window(constraints) -> str:
    tz = ZoneInfo(constraints.timezone)
    start, end = instant(constraints.window_start).astimezone(tz), instant(constraints.window_end).astimezone(tz)
    def clock(dt):
        return dt.strftime("%-I:%M %p").replace(":00", "").lower()
    return f"{start.strftime('%A %b %-d')}, {clock(start)}–{clock(end)} {start.tzname()}"


def trusted_provider_id(provider_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", provider_id):
        raise ValueError("Invalid provider id")
    return provider_id
