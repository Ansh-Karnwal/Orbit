"""portal_parse on saved portal pages (regenerate by rendering the portal; see html/ folder)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.portal_parse import (error_code, page_kind, parse_bookings, parse_confirmation,
                                       parse_slots)

HTML = Path(__file__).parent / "html"


def page(name: str) -> str:
    return (HTML / name).read_text(encoding="utf-8")


def test_confirmed_page():
    c = parse_confirmation(page("confirmed.html"))
    assert c is not None and c.confirmation_id.startswith("BK-")
    assert c.provider_id == "provider_b" and c.service == "dishwasher_repair"
    assert c.slot_start.isoformat() == "2026-10-20T21:30:00+00:00"
    assert c.slot_end.isoformat() == "2026-10-20T22:30:00+00:00"
    assert c.visit_charge_cents == 14500 and c.orbit_ref == "ORB-fix1"
    assert c.cancellation_terms == "Cancel free more than 12 hours ahead, $25 inside 12 hours."
    assert page_kind(page("confirmed.html")) == "confirmed"


def test_mismatch_page_is_reported_as_shown():
    c = parse_confirmation(page("mismatch.html"))
    assert c.visit_charge_cents == 16500
    assert c.slot_start.isoformat() == "2026-10-21T02:00:00+00:00"   # 16:00 PDT slot shifted +3 h


def test_no_confirmation_page():
    html = page("no_confirmation.html")
    assert parse_confirmation(html) is None and page_kind(html) == "received"


def test_lookup_pages():
    assert parse_confirmation(page("lookup.html")).orbit_ref == "ORB-fix1"
    assert parse_bookings(page("lookup_empty.html")) == []
    assert page_kind(page("lookup_empty.html")) == "lookup"


def test_slots_from_booking_form():
    slots = parse_slots(page("book.html"))
    assert [(s.start.isoformat(), s.label) for s in slots] == [
        ("2026-10-20T21:30:00+00:00", "2:30 PM – 3:30 PM PT"),
        ("2026-10-20T23:00:00+00:00", "4:00 PM – 5:00 PM PT")]
    assert page_kind(page("book.html")) == "booking_form"


def test_error_and_review_pages():
    assert page_kind(page("error_unavailable.html")) == "error"
    assert error_code(page("error_unavailable.html")) == "slot_unavailable"
    assert page_kind(page("review.html")) == "review"
    assert parse_confirmation(page("review.html")) is None


@pytest.mark.parametrize("html", [
    '<div data-booking><dd data-value="BK-1" data-field="confirmation_id">x</dd></div>',
    "<div data-booking><dd data-field='confirmation_id'>  BK-1 </dd></div>",
])
def test_tolerant_attribute_order_and_text_fallback(html):
    assert parse_bookings(html)[0]["confirmation_id"] == "BK-1"


def test_incomplete_booking_is_not_a_confirmation():
    assert parse_confirmation('<div data-booking><dd data-field="confirmation_id" '
                              'data-value="BK-1"></dd></div>') is None
