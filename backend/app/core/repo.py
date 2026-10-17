"""Owner: Victor. Sync repository — the only module that touches the DB.
Stub from CP0 — Phase 1 replaces every body; signatures are contract (§3.5)."""
from __future__ import annotations

from app.core.schemas import (Approval, ContextFact, EvidenceArtifact, FactStatus, InboundEvent,
                              Proposal, ProviderSpec, Task, TaskStatus, TimelineEvent, ToolAction,
                              VerificationResult)


def _todo(name: str):
    raise NotImplementedError(f"repo.{name}: Phase 1")


def get_task(task_id: str) -> Task:
    _todo("get_task")


def list_active_tasks() -> list[Task]:
    _todo("list_active_tasks")


def set_status(task_id: str, status: TaskStatus, reason: str = "") -> Task:
    _todo("set_status")


def get_providers(task_id: str) -> list[ProviderSpec]:
    _todo("get_providers")


def get_provider(task_id: str, provider_id: str) -> ProviderSpec:
    _todo("get_provider")


def find_task_by_handle(handle: str) -> tuple[str, str] | None:
    _todo("find_task_by_handle")


def list_facts(task_id: str, key_prefix: str | None = None,
               include_inactive: bool = False) -> list[ContextFact]:
    _todo("list_facts")


def get_active_fact(task_id: str, key: str) -> ContextFact | None:
    _todo("get_active_fact")


def insert_fact(fact: ContextFact) -> ContextFact:
    _todo("insert_fact")


def set_fact_status(fact_id: str, status: FactStatus) -> None:
    _todo("set_fact_status")


def add_evidence(ev: EvidenceArtifact) -> EvidenceArtifact:
    _todo("add_evidence")


def list_evidence(task_id: str, kind: str | None = None) -> list[EvidenceArtifact]:
    _todo("list_evidence")


def get_evidence(evidence_id: str) -> EvidenceArtifact:
    _todo("get_evidence")


def record_inbound(ev: InboundEvent) -> tuple[InboundEvent, bool]:
    _todo("record_inbound")


def create_approval_request(proposal: Proposal) -> Approval:
    _todo("create_approval_request")


def decide_approval(approval_id: str, decision: str, approver: str) -> Approval:
    _todo("decide_approval")


def get_latest_approval(task_id: str) -> Approval | None:
    _todo("get_latest_approval")


def list_approvals(task_id: str) -> list[Approval]:
    _todo("list_approvals")


def invalidate_approvals(task_id: str, reason: str) -> list[Approval]:
    _todo("invalidate_approvals")


def save_verification(v: VerificationResult) -> VerificationResult:
    _todo("save_verification")


def latest_verification(task_id: str) -> VerificationResult | None:
    _todo("latest_verification")


def emit(task_id: str, type: str, message: str, data: dict | None = None) -> TimelineEvent:
    _todo("emit")


def get_action_by_key(idempotency_key: str) -> ToolAction | None:
    _todo("get_action_by_key")


def save_action(a: ToolAction) -> ToolAction:
    _todo("save_action")
