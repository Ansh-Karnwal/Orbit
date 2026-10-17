from datetime import datetime

import pytest

from app.context.values import cents, instant, normalize_slots, usd_to_cents


@pytest.mark.parametrize("value", [True, 12.0, "12.5", -1, "NaN", "Infinity"])
def test_cents_reject_lossy_or_negative_money(value):
    with pytest.raises(ValueError):
        cents(value)


def test_decimal_usd_is_exact():
    assert usd_to_cents("145.01") == 14501


def test_naive_dates_rejected():
    with pytest.raises(ValueError):
        instant(datetime(2026, 10, 20))


def test_slots_canonicalized_and_invalid_order_rejected():
    assert normalize_slots([{"start": "2026-10-20T15:00:00-07:00", "end": "2026-10-20T16:00:00-07:00"}]) == [
        {"start": "2026-10-20T22:00:00Z", "end": "2026-10-20T23:00:00Z"}]
    with pytest.raises(ValueError):
        normalize_slots([{"start": "2026-10-20T23:00:00Z", "end": "2026-10-20T22:00:00Z"}])
