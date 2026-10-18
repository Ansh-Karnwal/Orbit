"""Evidence-only verification. The caller persists this result and enforces its verdict."""
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.schemas import BookingRequest, VerificationResult, Verdict, new_id, utcnow
from app.llm.client import LLMExtractionError, LLMUnavailable, structured
from app.verify.predicates import confirmation_from, evaluate, verdict_for
from app.verify.readonly import ReadOnlyRepo


class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=600)


def _request_reference(task, approval, evidence) -> tuple[str | None, list[str]]:
    """Read an optional full BookingRequest captured separately from portal content.

    The shared schema already defines BookingRequest, but CP0 does not promise that
    adapters capture it. Absence remains insufficient evidence; never infer a link
    from a confirmation's own reference.
    """
    if approval is None:
        return None, []
    references = {}
    for artifact in evidence:
        if artifact.task_id != task.id or artifact.kind != "browser_trace" or artifact.source not in {"orbit", "browser_use", "fixture_browser"}:
            continue
        if task.mode == "live" and artifact.is_fixture:
            continue
        if approval.decided_at is None or artifact.captured_at < approval.decided_at:
            continue
        raw = artifact.extracted.get("booking_request")
        if not isinstance(raw, dict):
            continue
        try:
            request = BookingRequest.model_validate(raw)
        except ValidationError:
            continue
        if (request.task_id == task.id and request.approval_id == approval.id and request.orbit_ref.strip()
                and request.proposal.compute_hash() == approval.proposal_hash):
            references.setdefault(request.orbit_ref, []).append(artifact.id)
    if len(references) != 1:
        return None, []
    reference = next(iter(references))
    return reference, references[reference]


def _template(verdict, predicates):
    failed = [p.detail for p in predicates if p.passed is False]
    missing = [p.detail for p in predicates if p.passed is None]
    if verdict == Verdict.PASS:
        fixture = " (fixture evidence)" if any("fixture evidence" in p.detail for p in predicates) else ""
        return f"PASS{fixture}: booking confirmation matches the approved terms and user constraints."
    details = failed if failed else missing
    return f"{verdict.value}: " + "; ".join(dict.fromkeys(details)) + "."


async def verify(task_id: str) -> VerificationResult:
    reads = ReadOnlyRepo()
    task = reads.get_task(task_id)
    providers = reads.get_providers(task_id)
    facts = reads.list_facts(task_id)
    approval = reads.get_latest_approval(task_id)
    artifacts = reads.list_evidence(task_id)
    reference, reference_ids = _request_reference(task, approval, artifacts)
    candidates = sorted((e for e in artifacts if e.task_id == task_id and e.kind == "portal_confirmation"
                         and e.source in {"browser_use", "fixture_browser"}), key=lambda e: e.captured_at, reverse=True)
    if reference_ids:
        recorded_at = min(e.captured_at for e in artifacts if e.id in reference_ids)
        candidates = [e for e in candidates if e.captured_at >= recorded_at]
    # Evaluate the newest evidence, including mismatches and malformed content.
    # Searching only for the desired reference could hide a later failed booking.
    artifact = candidates[0] if candidates else None
    confirmation = confirmation_from(artifact) if artifact else None
    predicates = evaluate(task, providers, facts, approval, confirmation, artifact, reference)
    if reference_ids:
        for predicate in predicates:
            if predicate.name in {"confirmation_present", "confirmation_consistent"}:
                predicate.evidence_ids.extend(reference_ids)
    if artifact and ((task.mode == "live" and artifact.is_fixture) or (artifact.source == "fixture_browser" and not artifact.is_fixture)):
        predicate = next(p for p in predicates if p.name == "confirmation_present")
        predicate.passed, predicate.detail = False, "Fixture evidence cannot substantiate a live booking"
    verdict = verdict_for(predicates)
    explanation = _template(verdict, predicates)
    try:
        result = await structured(Explanation,
            system=(Path(__file__).parents[1] / "llm/prompts/verify.txt").read_text(encoding="utf-8"),
            instructions=f"Explain deterministic verdict {verdict.value}; include that verdict verbatim. Use at most three sentences.",
            untrusted=[p.model_dump_json() for p in predicates], task_id=task_id)
        text = result.text.strip()
        unsafe_claim = verdict != Verdict.PASS and any(word in text.lower() for word in ("handled", "booking verified", "completed"))
        if verdict.value in text and not unsafe_claim and text.count(".") <= 3:
            explanation = text
    except (LLMUnavailable, LLMExtractionError):
        pass
    return VerificationResult(id=new_id("ver"), task_id=task_id, approval_id=approval.id if approval else None,
                              predicates=predicates, verdict=verdict, explanation=explanation, created_at=utcnow())
