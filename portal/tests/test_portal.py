"""Portal behaviour: slots, booking, confirmation markup, fault modes, lookup, no dedup."""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portal_core import create_app  # noqa: E402

# Saturday 2026-10-17, 11:00 PDT. Next 14 weekdays run Mon Oct 19 .. Thu Nov 5 (crosses DST end).
NOW = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
TUE = "2026-10-20"
B_SLOT = "2026-10-20T21:30:00Z"          # 14:30 PDT


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "portal.db", now_fn=lambda: NOW)) as c:
        yield c


def book_json(client, pid="provider_b", slot=B_SLOT, ref="ORB-test1"):
    return client.post(f"/api/p/{pid}/book", json={
        "slot_start": slot, "service": "dishwasher_repair", "customer_name": "Orbit Demo User",
        "customer_contact": "demo@example.com", "reference": ref})


def book_html(client, pid="provider_b", slot=B_SLOT, ref="ORB-test1"):
    return client.post(f"/p/{pid}/book", data={
        "slot": slot, "service": "dishwasher_repair", "customer_name": "Orbit Demo User",
        "customer_contact": "demo@example.com", "reference": ref})


def fields(html: str) -> dict[str, str]:
    return dict(re.findall(r'data-field="([a-z_]+)" data-value="([^"]*)"', html))


# ---------------------------------------------------------------- slots
def test_slots_for_next_weekdays_in_la_time(client):
    r = client.get("/api/p/provider_b/slots", params={"date": TUE})
    assert r.status_code == 200
    assert [s["start"] for s in r.json()["slots"]] == [B_SLOT, "2026-10-20T23:00:00Z"]
    assert r.json()["slots"][0]["label"] == "2:30 PM – 3:30 PM PT"


def test_slots_respect_dst_change(client):
    # Tue Nov 3 is after DST ends: 14:30 PST == 22:30Z.
    r = client.get("/api/p/provider_b/slots", params={"date": "2026-11-03"})
    assert r.json()["slots"][0]["start"] == "2026-11-03T22:30:00Z"


def test_no_slots_on_weekends_or_beyond_horizon(client):
    assert client.get("/api/p/provider_b/slots", params={"date": "2026-10-18"}).json()["slots"] == []
    assert client.get("/api/p/provider_b/slots", params={"date": "2026-11-06"}).json()["slots"] == []
    assert client.get("/api/p/provider_b/slots", params={"date": "2026-11-05"}).json()["slots"]


def test_book_page_has_slot_radios(client):
    html = client.get("/p/provider_b/book", params={"date": TUE}).text
    assert f'value="{B_SLOT}" data-slot-start="{B_SLOT}" data-slot-end="2026-10-20T22:30:00Z"' in html
    assert "2:30 PM – 3:30 PM PT" in html and "Your reference (optional)" in html
    assert "Demo portal for LA Hacks" in html


def test_provider_page_shows_hidden_trip_fee(client):
    html = client.get("/p/provider_a").text
    assert "$120.00" in html and "Trip charge: $70.00" in html
    assert "Parts and labor quoted after diagnosis" in client.get("/p/provider_b").text


def test_no_payment_fields_anywhere(client):
    for path in ["/", "/p/provider_a", "/p/provider_b", f"/p/provider_b/book?date={TUE}"]:
        html = client.get(path).text.lower()
        assert not re.search(r'name="[^"]*(card|cvv|cvc|payment)', html), path


# ---------------------------------------------------------------- booking
def test_html_review_then_confirm(client):
    form = {"slot": B_SLOT, "service": "dishwasher_repair", "customer_name": "Orbit Demo User",
            "customer_contact": "demo@example.com", "reference": "ORB-abc"}
    review = client.post("/p/provider_b/review", data=form)
    assert review.status_code == 200 and 'id="confirm-booking"' in review.text
    assert client.get("/admin/state").json()["bookings"] == []          # review doesn't book
    r = client.post("/p/provider_b/book", data=form)
    assert r.status_code == 200 and "Booking confirmed" in r.text
    f = fields(r.text)
    assert re.fullmatch(r"BK-[A-Z0-9]{4}", f["confirmation_id"])
    assert f == {**f, "provider_id": "provider_b", "service": "dishwasher_repair",
                 "slot_start": B_SLOT, "slot_end": "2026-10-20T22:30:00Z",
                 "visit_charge_cents": "14500", "reference": "ORB-abc",
                 "cancellation_terms": "Free more than 12 hours ahead; $25 within 12 hours"}
    assert "$145.00" in r.text


def test_booking_removes_slot(client):
    assert book_json(client).status_code == 201
    starts = [s["start"] for s in client.get("/api/p/provider_b/slots", params={"date": TUE}).json()["slots"]]
    assert B_SLOT not in starts and len(starts) == 1


def test_booking_taken_slot_is_unavailable(client):
    book_json(client)
    r = book_html(client, ref="ORB-other")
    assert r.status_code == 409 and 'data-error="slot_unavailable"' in r.text
    assert "Booking confirmed" not in r.text
    assert book_json(client, ref="ORB-other").json()["error"] == "slot_unavailable"


def test_no_dedup_by_reference(client):
    assert book_json(client, ref="ORB-same").status_code == 201
    assert book_json(client, slot="2026-10-20T23:00:00Z", ref="ORB-same").status_code == 201
    assert len(client.get("/api/p/provider_b/bookings", params={"ref": "ORB-same"}).json()["bookings"]) == 2


def test_lookup_by_reference(client):
    conf = book_json(client, ref="ORB-look").json()["booking"]["confirmation_id"]
    html = client.get("/p/provider_b/lookup", params={"ref": "ORB-look"}).text
    assert fields(html)["confirmation_id"] == conf
    assert "No booking found" in client.get("/p/provider_b/lookup", params={"ref": "ORB-none"}).text
    assert client.get("/api/p/provider_b/bookings", params={"ref": "ORB-none"}).json()["bookings"] == []


# ---------------------------------------------------------------- fault modes
def test_fault_mismatch_alters_display_not_record(client):
    client.post("/admin/fault", json={"mode": "mismatch"})
    f = fields(book_html(client, ref="ORB-mm").text)
    assert f["slot_start"] == "2026-10-21T00:30:00Z" and f["visit_charge_cents"] == "16500"
    stored = client.get("/api/p/provider_b/bookings", params={"ref": "ORB-mm"}).json()["bookings"][0]
    assert stored["slot_start"] == B_SLOT and stored["visit_charge_cents"] == 14500
    j = book_json(client, slot="2026-10-20T23:00:00Z", ref="ORB-mm2").json()
    assert j["booking"]["visit_charge_cents"] == 16500


def test_fault_no_confirmation_records_but_hides_id(client):
    client.post("/admin/fault", json={"mode": "no_confirmation"})
    r = book_html(client, ref="ORB-nc")
    assert "We received your request and will be in touch" in r.text
    assert "confirmation_id" not in r.text and "BK-" not in r.text
    assert len(client.get("/admin/state").json()["bookings"]) == 1
    j = book_json(client, slot="2026-10-20T23:00:00Z", ref="ORB-nc2")
    assert j.status_code == 202 and "confirmation_id" not in j.text


def test_fault_timeout_records_before_sleeping(client):
    client.post("/admin/fault", json={"mode": "timeout_after_submit", "delay_s": 0.3})
    t0 = time.monotonic()
    r = book_json(client, ref="ORB-to")
    assert time.monotonic() - t0 >= 0.3 and r.status_code == 201
    assert client.get("/api/p/provider_b/bookings", params={"ref": "ORB-to"}).json()["bookings"]


def test_fault_down_blocks_booking_only(client):
    client.post("/admin/fault", json={"mode": "down"})
    assert book_html(client).status_code == 503
    assert book_json(client).status_code == 503
    assert client.post("/p/provider_b/review", data={"slot": B_SLOT}).status_code == 503
    assert client.get("/api/p/provider_b/slots", params={"date": TUE}).status_code == 200
    assert client.get("/p/provider_b/lookup", params={"ref": "x"}).status_code == 200
    assert client.get("/admin/state").json()["bookings"] == []


def test_admin_reset_clears_bookings_and_fault(client):
    client.post("/admin/fault", json={"mode": "mismatch"})
    book_json(client)
    client.post("/admin/reset")
    state = client.get("/admin/state").json()
    assert state["bookings"] == [] and state["fault"]["mode"] == "none"


def test_unknown_provider_404(client):
    assert client.get("/p/provider_z").status_code == 404
    assert client.get("/api/p/provider_z/slots", params={"date": TUE}).status_code == 404
