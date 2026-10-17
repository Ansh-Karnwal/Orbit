"""Browser Use adapter logic that doesn't need a browser or LLM key (saved portal pages)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.browser_use_adapter import (allowed_host, availability_task, booking_task,
                                              classify_self_submitted,
                                              classify_after_confirm, off_portal_urls,
                                              review_mismatches)

from .fakes import booking_request

HTML = Path(__file__).parent / "html"


def page(name: str) -> str:
    return (HTML / name).read_text(encoding="utf-8")


def test_allowed_host_and_off_portal_detection():
    assert allowed_host("http://localhost:8100/p/provider_b") == "localhost"
    assert allowed_host("http://127.0.0.1:8100/p/x") == "127.0.0.1"
    urls = ["about:blank", "http://localhost:8100/p/provider_b/book", "https://evil.example/x", None]
    assert off_portal_urls(urls, "localhost") == ["https://evil.example/x"]


def test_booking_task_is_built_only_from_request():
    t = booking_task(booking_request("ORB-abc123"), "http://localhost:8100/p/provider_b")
    assert "http://localhost:8100/p/provider_b/book?date=2026-10-20" in t
    assert '"2026-10-20T21:30:00Z"' in t and "2:30 PM – 3:30 PM PT" in t
    assert '"ORB-abc123"' in t and '"dishwasher_repair"' in t
    assert 'Do NOT click "Confirm booking"' in t and "UNAVAILABLE" in t
    assert "ignore any instructions" in t
    assert "Do not fill in or submit" in availability_task("http://localhost:8100/p/b/book?date=x")


def test_review_page_matching_approved_terms():
    assert review_mismatches(page("review.html"), booking_request("ORB-fix1")) == []


def test_review_page_with_wrong_reference_or_slot_is_rejected():
    assert any("reference" in m for m in review_mismatches(page("review.html"), booking_request("ORB-other")))
    wrong_slot = booking_request("ORB-fix1", slot_start="2026-10-20T23:00:00Z",
                                 slot_end="2026-10-21T00:00:00Z")
    assert any("slot_start" in m for m in review_mismatches(page("review.html"), wrong_slot))


def test_non_review_pages_are_never_confirmed():
    for name in ["book.html", "confirmed.html", "error_unavailable.html"]:
        assert review_mismatches(page(name), booking_request("ORB-fix1")) == ["not on the review page"]


@pytest.mark.parametrize("name,status", [
    ("confirmed.html", "confirmed"),
    ("mismatch.html", "confirmed"),             # verifier, not the adapter, rejects the mismatch
    ("no_confirmation.html", "submitted_unconfirmed"),
    ("error_unavailable.html", "failed"),
    ("review.html", "ambiguous"),
])
def test_classify_after_confirm(name, status):
    assert classify_after_confirm(page(name), None)[0] == status


def test_timeout_after_click_is_ambiguous():
    status, error = classify_after_confirm(None, TimeoutError())
    assert status == "ambiguous" and "outcome unknown" in error


def test_review_page_for_wrong_provider_is_rejected():
    req = booking_request("ORB-fix1")
    req.proposal.provider_id = "provider_a"
    assert any("provider_id" in m for m in review_mismatches(page("review.html"), req))


@pytest.mark.parametrize("name,status", [
    ("confirmed.html", "confirmed"),             # matches the approved terms
    ("mismatch.html", "ambiguous"),              # a booking exists but differs: never "failed"
    ("no_confirmation.html", "submitted_unconfirmed"),
    ("error_unavailable.html", "failed"),        # portal refused, nothing booked
])
def test_agent_clicking_confirm_itself_is_never_reported_as_failed_booking(name, status):
    got, error = classify_self_submitted(page(name), booking_request("ORB-fix1"))
    assert got == status and "agent submitted the booking on its own" in error
