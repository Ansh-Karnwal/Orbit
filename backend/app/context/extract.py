"""Extract quote data, then deterministically resolve and ingest each observation."""
import json
from pathlib import Path

from app.core import repo
from app.core.schemas import IngestResult, PlanStep, StepKind, new_id, utcnow
from app.context.facts import ingest_fact
from app.context.parser import parse_quote, quote_text, resolve_slots
from app.context.quote import ProviderQuoteExtraction
from app.context.values import usd_to_cents
from app.llm.client import LLMExtractionError, LLMUnavailable, structured


def quote_values(quote: ProviderQuoteExtraction, constraints, history: dict) -> dict:
    values = {}
    if quote.service_supported is not None:
        values["service_supported"] = quote.service_supported
    if quote.base_charge_usd is not None:
        values["base_charge_cents"] = usd_to_cents(quote.base_charge_usd)
    if quote.extra_fees is not None:
        values["extra_fees"] = [{"name": f.name.strip(), "cents": usd_to_cents(f.usd)} for f in quote.extra_fees]
        historical_base = history.get("base_charge_cents", history.get("visit_charge_cents"))
        if "base_charge_cents" not in values and historical_base is not None:
            values["base_charge_cents"] = historical_base
    if quote.total_visit_charge_usd is not None:
        values["visit_charge_cents"] = usd_to_cents(quote.total_visit_charge_usd)
    elif "base_charge_cents" in values and quote.fee_scope != "diagnostic_visit_excluding_travel":
        values["visit_charge_cents"] = values["base_charge_cents"] + sum(f["cents"] for f in values.get("extra_fees", []))
    if quote.fee_scope is not None:
        values["fee_scope"] = quote.fee_scope
    if quote.slots is not None:
        values["slots_offered"] = resolve_slots(quote.slots, constraints)
    if quote.cancellation_terms is not None:
        values["cancellation_terms"] = quote.cancellation_terms.strip()
    if quote.repair_cost_after_diagnosis is not None:
        values["repair_cost_known"] = not quote.repair_cost_after_diagnosis
    return values


async def extract_provider_facts(task_id: str, provider_id: str, text: str, source_id: str) -> list[IngestResult]:
    from app.context.assembler import assemble
    repo.get_provider(task_id, provider_id)
    task = repo.get_task(task_id)
    if not quote_text(text):
        return []
    now = utcnow()
    step = PlanStep(id=new_id("stp"), task_id=task_id, kind=StepKind.EXTRACT_QUOTE,
                    provider_id=provider_id, idempotency_key=f"extract:{source_id}", created_at=now, updated_at=now)
    packet = assemble(task_id, step)
    fallback = parse_quote(text, task.constraints.service)
    try:
        quote = await structured(ProviderQuoteExtraction,
            system=(Path(__file__).parents[1] / "llm/prompts/extract.txt").read_text(encoding="utf-8"),
            instructions="Extract the provider's current message. Trusted task constraints: " +
                         task.constraints.model_dump_json() + ". Only return quote data.",
            untrusted=[text, json.dumps({"provider_facts": [f.model_dump(mode="json") for f in packet.facts]})], task_id=task_id)
        # Deterministic conservative guard also applies to model extraction.
        if fallback.fee_scope == "unknown":
            quote.base_charge_usd = quote.total_visit_charge_usd = None
            quote.extra_fees = None
            quote.fee_scope = "unknown"
    except (LLMUnavailable, LLMExtractionError):
        quote = fallback
    history = {f.key.split(".", 1)[1]: f.value for f in packet.facts}
    values = quote_values(quote, task.constraints, history)
    # Use original receipt time where the shared repository exposes it.
    observed = None
    lookup = getattr(repo, "get_inbound", None) if source_id.startswith("inb_") else repo.get_evidence
    if lookup is not None:
        source = lookup(source_id)
        observed = getattr(source, "received_at", None) or getattr(source, "captured_at", None)
    results = []
    for field, value in values.items():
        scope = quote.fee_scope
        if field == "fee_scope" and any("contradiction: diagnostic only" in n for n in fallback.confidence_notes):
            scope = "diagnostic only; includes repair"
        results.append(ingest_fact(task_id, f"{provider_id}.{field}", value, source_id=source_id,
                                   scope=scope, observed_at=observed))
    # A real reply supersedes a recorded timeout.
    if values and history.get("no_reply") is True:
        results.append(ingest_fact(task_id, f"{provider_id}.no_reply", False, source_id=source_id, observed_at=observed))
    return results
