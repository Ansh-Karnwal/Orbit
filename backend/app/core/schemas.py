"""Orbit shared contract. Owned by Victor. Change only by team agreement."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------- enums
class TaskStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    BLOCKED = "BLOCKED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class FactStatus(str, Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class StepKind(str, Enum):
    SEND_INQUIRY = "send_inquiry"
    AWAIT_REPLY = "await_reply"
    EXTRACT_QUOTE = "extract_quote"
    COMPARE_QUOTES = "compare_quotes"
    READ_AVAILABILITY = "read_availability"
    REQUEST_APPROVAL = "request_approval"
    SUBMIT_BOOKING = "submit_booking"
    RECONCILE_BOOKING = "reconcile_booking"
    VERIFY = "verify"
    SUMMARIZE = "summarize"


class StepState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ClaimLevel(str, Enum):
    MESSAGE_SUBMITTED = "message_submitted"
    MESSAGE_DELIVERED = "message_delivered"
    SLOT_OFFERED = "slot_offered"
    BOOKING_REQUEST_SUBMITTED = "booking_request_submitted"
    BOOKING_VERIFIED = "booking_verified"  # only the verifier/completion gate may assert this


Mode = Literal["fixture", "live"]
AdapterName = Literal[
    "photon", "browser_use", "creao", "fixture_messaging", "fixture_browser", "demo", "orbit"
]
EvidenceKind = Literal[
    "message_out", "message_in", "delivery_receipt", "screenshot", "browser_trace",
    "availability", "portal_confirmation", "creao_output",
]


# ---------------------------------------------------------------- intake
class Constraints(BaseModel):
    service: str = "dishwasher_repair"
    window_start: datetime
    window_end: datetime
    timezone: str = "America/Los_Angeles"
    max_visit_charge_cents: int
    require_diagnostic_fee_confirmed: bool = True
    require_cancellation_terms: bool = True
    approval_policy: Literal["before_booking"] = "before_booking"


class Limits(BaseModel):
    max_tool_actions: int = 40
    max_runtime_s: int = 1800
    max_llm_calls: int = 60
    reply_timeout_s: int = 600


class ProviderSpec(BaseModel):
    id: str                                   # "provider_a"
    name: str
    channel: Literal["imessage", "sms", "fixture"] = "fixture"
    handle: str                               # live: phone/handle; fixture: "fixture:provider_a"
    portal_url: str | None = None             # e.g. http://localhost:8100/p/provider_b


class TaskCreate(BaseModel):
    outcome_text: str
    constraints: Constraints
    providers: list[ProviderSpec]
    limits: Limits = Field(default_factory=Limits)
    mode: Mode = "fixture"
    source: Literal["manual", "creao", "demo_seed"] = "manual"
    creao_ref: str | None = None


class Task(BaseModel):
    id: str
    outcome_text: str
    constraints: Constraints
    limits: Limits
    mode: Mode
    status: TaskStatus
    status_reason: str = ""
    source: str = "manual"
    creao_ref: str | None = None
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- context
class ContextFact(BaseModel):
    id: str
    task_id: str
    key: str                                  # see §3.8
    value: Any
    currency: str | None = None
    scope: str | None = None
    source_id: str                            # EvidenceArtifact.id or InboundEvent.id
    observed_at: datetime
    valid_until: datetime | None = None
    status: FactStatus
    version: int
    supersedes: str | None = None             # id of previous version


class Conflict(BaseModel):
    kind: Literal["value_changed", "budget_violation", "window_violation",
                  "missing_required", "contradiction"]
    key: str
    provider_id: str | None = None
    old_value: Any = None
    new_value: Any = None
    detail: str


class IngestResult(BaseModel):
    fact: ContextFact
    superseded: ContextFact | None = None
    conflicts: list[Conflict] = Field(default_factory=list)
    changed: bool = True                      # False if identical value already active (no new version)


class ContextPacket(BaseModel):
    task_id: str
    step_kind: StepKind
    outcome: str
    constraints: Constraints
    domain_rules: list[str]
    facts: list[ContextFact]
    unresolved: list[Conflict]
    allowed_scope: list[str]
    required_output: dict[str, Any]
    required_evidence: list[str]


# ---------------------------------------------------------------- plan & execution
class PlanStep(BaseModel):
    id: str
    task_id: str
    kind: StepKind
    provider_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    state: StepState = StepState.PENDING
    attempts: int = 0
    max_attempts: int = 3
    idempotency_key: str
    not_before: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    plan_version: int = 1
    created_at: datetime
    updated_at: datetime


class ToolAction(BaseModel):
    id: str
    task_id: str
    step_id: str
    adapter: AdapterName
    operation: str                            # "send" | "read_availability" | "submit_booking" | "find_booking"
    idempotency_key: str
    request: dict[str, Any]
    status: Literal["started", "succeeded", "failed", "ambiguous"]
    provider_ref: str | None = None
    result: dict[str, Any] | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None


class InboundEvent(BaseModel):
    id: str
    source: Literal["photon", "fixture", "demo"]
    external_id: str                          # dedup key together with source
    task_id: str | None = None
    provider_id: str | None = None
    sender_handle: str | None = None
    text: str
    payload: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime
    processed: bool = False


# ---------------------------------------------------------------- approval
class Proposal(BaseModel):
    task_id: str
    provider_id: str
    provider_name: str
    service: str
    slot_start: datetime
    slot_end: datetime
    visit_charge_cents: int
    fee_scope: str
    cancellation_terms: str
    repair_cost_known: bool = False
    terms_version: int                        # max version of the facts it was built from
    source_fact_ids: list[str]

    def compute_hash(self) -> str:
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class Approval(BaseModel):
    id: str
    task_id: str
    proposal: Proposal
    proposal_hash: str
    status: Literal["requested", "approved", "rejected", "invalidated", "expired"]
    approver: str | None = None
    requested_at: datetime
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    invalidated_reason: str | None = None


class ApprovalDecisionIn(BaseModel):
    proposal_hash: str
    decision: Literal["approved", "rejected"]
    approver: str = "demo_user"


# ---------------------------------------------------------------- evidence
class ConfirmationExtract(BaseModel):
    confirmation_id: str
    provider_id: str
    service: str
    slot_start: datetime
    slot_end: datetime
    visit_charge_cents: int
    cancellation_terms: str
    orbit_ref: str


class EvidenceArtifact(BaseModel):
    id: str
    task_id: str
    kind: EvidenceKind
    source: AdapterName
    uri: str | None = None                    # path relative to ARTIFACT_DIR; served at /artifacts/{id}
    mime_type: str | None = None
    sha256: str | None = None
    extracted: dict[str, Any] = Field(default_factory=dict)
    claim_level: ClaimLevel | None = None
    is_fixture: bool
    provider_ref: str | None = None
    captured_at: datetime


# ---------------------------------------------------------------- adapter results
class SendResult(BaseModel):
    provider_ref: str | None = None
    status: Literal["submitted", "delivered", "failed"]
    evidence_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class Slot(BaseModel):
    start: datetime
    end: datetime
    label: str = ""


class AvailabilityResult(BaseModel):
    slots: list[Slot]
    evidence_ids: list[str] = Field(default_factory=list)
    session_ref: str | None = None
    error: str | None = None


class BookingRequest(BaseModel):
    task_id: str
    proposal: Proposal
    approval_id: str
    orbit_ref: str                            # derived from the step idempotency key; typed into the portal form
    customer_name: str = "Orbit Demo User"
    customer_contact: str = "demo@example.com"


class BookingResult(BaseModel):
    status: Literal["confirmed", "submitted_unconfirmed", "ambiguous", "failed"]
    confirmation: ConfirmationExtract | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    session_ref: str | None = None            # Browser Use session/trace reference
    error: str | None = None


# ---------------------------------------------------------------- verification
class PredicateResult(BaseModel):
    name: str
    passed: bool | None                       # None = insufficient evidence
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    id: str
    task_id: str
    approval_id: str | None
    predicates: list[PredicateResult]
    verdict: Verdict
    explanation: str
    created_at: datetime


# ---------------------------------------------------------------- timeline & views
class TimelineEvent(BaseModel):
    id: str
    task_id: str
    seq: int                                  # per-task, strictly increasing
    type: str                                 # see §3.7
    message: str                              # human-readable, safe to show in UI
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime


class TaskView(BaseModel):
    task: Task
    providers: list[ProviderSpec]
    facts: list[ContextFact]                  # ALL versions incl. superseded
    eligibility: dict[str, list[str]]         # provider_id -> disqualification reasons ([] = eligible)
    steps: list[PlanStep]
    approvals: list[Approval]
    current_proposal: Proposal | None
    evidence: list[EvidenceArtifact]
    verification: VerificationResult | None
    timeline: list[TimelineEvent]             # last 200, ascending seq
    integrations: dict[str, str]              # {"photon": "live" | "fixture" | "blocked: reason", ...}


class DemoInjectIn(BaseModel):
    task_id: str
    provider_id: str
    text: str
    external_id: str | None = None            # pass the same value twice to test dedup


class PortalFaultIn(BaseModel):
    mode: Literal["none", "timeout_after_submit", "mismatch", "no_confirmation", "down"]
