"""Owner: Karthik. Stub from CP0 — replace (naive regex, no LLM)."""
from __future__ import annotations

import re

from app.context.facts import ingest_fact
from app.core.schemas import IngestResult

_DOLLARS = re.compile(r"\$(\d{2,5})")


async def extract_provider_facts(task_id: str, provider_id: str, text: str,
                                 source_id: str) -> list[IngestResult]:
    out: list[IngestResult] = []
    amounts = [int(a) for a in _DOLLARS.findall(text)]
    if amounts:
        # Stub heuristic: the largest amount is the total ("$70 trip charge ... $190 total").
        out.append(ingest_fact(task_id, f"{provider_id}.visit_charge_cents", max(amounts) * 100,
                               source_id=source_id, currency="USD"))
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if "cancel" in sentence.lower():
            out.append(ingest_fact(task_id, f"{provider_id}.cancellation_terms", sentence.strip(),
                                   source_id=source_id))
            break
    return out
