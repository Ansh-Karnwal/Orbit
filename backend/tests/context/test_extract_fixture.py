from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from app.context.domain import load_pack
from app.context.parser import parse_quote, resolve_slots
from app.context.values import usd_to_cents


@pytest.mark.parametrize("example", load_pack().examples, ids=lambda x: x.name)
def test_domain_examples(example):
    quote = parse_quote(example.message)
    actual = {}
    for field in ("service_supported", "fee_scope", "cancellation_terms"):
        value = getattr(quote, field)
        if value is not None:
            actual[field] = value
    if quote.base_charge_usd is not None:
        actual["base_charge_cents"] = usd_to_cents(quote.base_charge_usd)
    if quote.extra_fees:
        actual["extra_fees"] = [{"name": x.name, "cents": usd_to_cents(x.usd)} for x in quote.extra_fees]
    if quote.total_visit_charge_usd is not None:
        actual["visit_charge_cents"] = usd_to_cents(quote.total_visit_charge_usd)
    elif quote.base_charge_usd is not None:
        actual["visit_charge_cents"] = actual["base_charge_cents"] + sum(x["cents"] for x in actual.get("extra_fees", []))
    if quote.slots:
        actual["slots_count"] = len(quote.slots)
    if quote.repair_cost_after_diagnosis is not None:
        actual["repair_cost_known"] = not quote.repair_cost_after_diagnosis
    for key, value in example.expected.items():
        assert actual.get(key) == value, (key, quote)
    if example.name in {"starting_price", "ambiguous", "injection"}:
        assert "visit_charge_cents" not in actual


@pytest.mark.parametrize("day,utc_hour", [("2026-10-20", 21), ("2026-11-03", 22)])
def test_tuesday_slots_resolve_across_dst(day, utc_hour):
    constraints = SimpleNamespace(timezone="America/Los_Angeles", window_start=datetime.fromisoformat(day + "T21:00:00+00:00"))
    slots = resolve_slots(parse_quote("Tuesday 2:30–3:30pm").slots, constraints)
    assert slots[0]["start"] == f"{day}T{utc_hour}:30:00Z"


def test_rejects_distant_dates_and_dst_fold():
    from app.context.quote import QuoteSlot
    constraints = SimpleNamespace(timezone="America/Los_Angeles", window_start=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert resolve_slots([QuoteSlot(day_text="2027-01-01", start_local="14:00", end_local="15:00")], constraints) == []
    assert resolve_slots([QuoteSlot(day_text="2026-11-01", start_local="01:00", end_local="02:00")], constraints) == []


def test_not_including_repair_does_not_turn_diagnosis_into_a_known_repair_price():
    quote = parse_quote("Dishwasher diagnostic visit is $145 including travel. It does not include repairs. Parts and labor are quoted after diagnosis.")
    assert quote.fee_scope == "diagnostic_visit_including_travel"
    assert quote.repair_cost_after_diagnosis is True


def test_positive_repair_scope_conflicting_with_diagnostic_only_is_ambiguous():
    quote = parse_quote("Dishwasher diagnostic visit only is $145 including travel. This includes repair.")
    assert quote.fee_scope == "unknown"
    assert any("contradiction" in note for note in quote.confidence_notes)
