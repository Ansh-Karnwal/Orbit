"""Small per-action packets. Historical versions never enter model context."""
from app.core import repo
from app.core.schemas import (Approval, AvailabilityResult, BookingResult, ContextPacket,
                              InboundEvent, PlanStep, Proposal, SendResult, StepKind, VerificationResult)
from app.context.conflicts import current_facts, detect_conflicts
from app.context.domain import load_pack
from app.context.quote import ProviderQuoteExtraction

SCOPES = {
    "send_inquiry": ["compose_inquiry"], "await_reply": ["read_message"],
    "extract_quote": ["read_message", "propose_facts"], "compare_quotes": ["compare_eligible_quotes"],
    "read_availability": ["read_provider_availability"], "request_approval": ["present_exact_proposal"],
    "submit_booking": ["submit_only_approved_booking"], "reconcile_booking": ["find_existing_booking"],
    "verify": ["read_evidence", "evaluate_predicates"], "summarize": ["summarize_verified_evidence"],
}
EVIDENCE = {
    "send_inquiry": ["message_out"], "await_reply": ["message_in"], "extract_quote": ["message_in"],
    "compare_quotes": ["provenanced_quote_facts"], "read_availability": ["availability"],
    "request_approval": ["proposal_hash", "source_fact_ids"], "submit_booking": ["approved_proposal", "portal_confirmation"],
    "reconcile_booking": ["portal_confirmation", "matching_orbit_ref"],
    "verify": ["approved_proposal", "portal_confirmation", "approval_bound_orbit_ref"], "summarize": ["PASS_verification"],
}
OUTPUTS = {"send_inquiry": SendResult, "await_reply": InboundEvent, "extract_quote": ProviderQuoteExtraction,
           "compare_quotes": Proposal, "read_availability": AvailabilityResult, "request_approval": Approval,
           "submit_booking": BookingResult, "reconcile_booking": BookingResult, "verify": VerificationResult}


def assemble(task_id: str, step: PlanStep) -> ContextPacket:
    if step.task_id != task_id:
        raise ValueError("Step belongs to a different task")
    task, pack = repo.get_task(task_id), load_pack()
    active = current_facts(repo.list_facts(task_id))
    providers = {p.id for p in repo.get_providers(task_id)}
    if step.provider_id is not None and step.provider_id not in providers:
        raise ValueError("Unknown step provider")
    kind = step.kind.value
    all_providers = step.kind in {StepKind.COMPARE_QUOTES, StepKind.VERIFY, StepKind.SUMMARIZE}
    selected = providers if all_providers else ({step.provider_id} if step.provider_id else set())
    facts = sorted((f for f in active.values() if f.key.split(".", 1)[0] in selected), key=lambda f: f.key)
    if step.kind == StepKind.SEND_INQUIRY:
        facts = []
    rules = [pack.fee_distinctions[4], pack.fee_distinctions[0], pack.fee_distinctions[1]]
    if step.kind == StepKind.EXTRACT_QUOTE:
        rules += pack.fee_distinctions[2:4]
    elif step.kind in {StepKind.COMPARE_QUOTES, StepKind.READ_AVAILABILITY}:
        rules += pack.comparison_rules
    else:
        rules += ["Booking requires approval of exact provider, service, slot, charge, scope and cancellation terms.",
                  "Only PASS verification supports the claim Booking verified; fixture evidence must be labeled."]
    output = OUTPUTS[kind].model_json_schema() if kind in OUTPUTS else {"type": "string", "description": "Verified final summary"}
    return ContextPacket(task_id=task_id, step_kind=step.kind, outcome=task.outcome_text,
        constraints=task.constraints, domain_rules=rules, facts=facts,
        unresolved=[c for c in detect_conflicts(task_id) if c.provider_id in selected],
        allowed_scope=SCOPES[kind], required_output=output, required_evidence=EVIDENCE[kind])
