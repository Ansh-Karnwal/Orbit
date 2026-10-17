import asyncio

import pytest

pytest.importorskip("app.core.schemas", reason="Waiting for Victor's CP0")
from app.context.facts import ingest_fact
from app.context.summary import summarize
from app.verify.verifier import verify
from tests.verify.test_verifier import booking_evidence


def test_honest_summary_with_unknown_parts_and_labor(memory_repo):
    memory_repo.seed_provider("provider_a", 12000)
    ingest_fact("tsk_test", "provider_a.visit_charge_cents", 19000, source_id=memory_repo.source())
    booking_evidence(memory_repo)
    result = asyncio.run(verify("tsk_test"))
    summary = asyncio.run(summarize("tsk_test", result))
    for fragment in ("Booking verified (fixture evidence)", "Bayside Appliance Service", "Tuesday Oct 20", "PDT", "$145.00",
                     "including travel", "Free cancellation with 24 hours notice", "BK-test", "Ace Appliance Repair was rejected",
                     "$190.00 > $150.00", "Parts and labor will be quoted after diagnosis", "diagnostic visit only"):
        assert fragment in summary
    assert "$120.00" not in summary


def test_summary_requires_pass(memory_repo):
    booking_evidence(memory_repo, confirmation=False)
    result = asyncio.run(verify("tsk_test"))
    with pytest.raises(ValueError, match="PASS"):
        asyncio.run(summarize("tsk_test", result))
