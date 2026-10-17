import asyncio
import os
from pathlib import Path

import pytest

from app.context.quote import ProviderQuoteExtraction
from app.llm.client import status, structured

pytestmark = [pytest.mark.live_llm, pytest.mark.skipif(os.getenv("RUN_LIVE_LLM_TESTS") != "1", reason="Live API tests require explicit opt-in")]


@pytest.mark.parametrize("message,total", [
    ("Hi! Dishwasher repair visit is $120. I can do Tuesday 3–4pm. Free cancellation with 24 hours notice.", "120"),
    ("Diagnostic visit is $145 including travel. Tuesday 2:30–3:30pm or 4–5pm. Cancel free more than 12 hours ahead, $25 inside 12 hours. Parts and labor are quoted after diagnosis.", "145"),
    ("Sorry, I forgot — there's a $70 trip charge on top, so $190 total.", "190"),
    ("We can diagnose your dishwasher for one forty-five dollars including travel. Tuesday 4–5pm. Free cancellation.", "145"),
])
def test_live_quote_extraction(message, total):
    if status() != "live":
        pytest.skip(status())
    prompt = Path(__file__).parents[2] / "app/llm/prompts/extract.txt"
    result = asyncio.run(structured(ProviderQuoteExtraction, system=prompt.read_text(), instructions="Extract explicit quote facts only.", untrusted=[message]))
    from decimal import Decimal
    assert Decimal(result.total_visit_charge_usd) == Decimal(total)
