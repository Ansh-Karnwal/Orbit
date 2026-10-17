"""In-memory repo using Victor's actual shared models, never copies of schemas."""
from datetime import datetime, timezone

import pytest


class MemoryRepo:
    def __init__(self):
        from app.core.schemas import Constraints, Limits, ProviderSpec, Task, TaskStatus
        now = datetime.now(timezone.utc)
        self.task = Task(id="tsk_test", outcome_text="Arrange dishwasher repair", constraints=Constraints(
            window_start=datetime(2026, 10, 20, 21, tzinfo=timezone.utc), window_end=datetime(2026, 10, 21, 0, tzinfo=timezone.utc),
            timezone="America/Los_Angeles", max_visit_charge_cents=15000), limits=Limits(), mode="fixture",
            status=TaskStatus.RUNNING, created_at=now, updated_at=now)
        self.providers = [ProviderSpec(id="provider_a", name="Ace Appliance Repair", handle="fixture:provider_a"),
                          ProviderSpec(id="provider_b", name="Bayside Appliance Service", handle="fixture:provider_b")]
        self.facts = []
        self.evidence = []
        self.approvals = []
        self.inbound = {}
        self.verifications = []
        self.writes = []

    def get_task(self, task_id):
        assert task_id == self.task.id
        return self.task

    def get_providers(self, task_id):
        self.get_task(task_id)
        return self.providers

    def get_provider(self, task_id, provider_id):
        return next(p for p in self.get_providers(task_id) if p.id == provider_id)

    def list_facts(self, task_id, key_prefix=None, include_inactive=False):
        from app.core.schemas import FactStatus
        return [f for f in self.facts if f.task_id == task_id and (not key_prefix or f.key.startswith(key_prefix))
                and (include_inactive or f.status in {FactStatus.CONFIRMED, FactStatus.PROPOSED})]

    def get_active_fact(self, task_id, key):
        return max((f for f in self.list_facts(task_id) if f.key == key), key=lambda f: f.version, default=None)

    def insert_fact(self, fact):
        self.writes.append("fact")
        self.facts.append(fact)
        return fact

    def set_fact_status(self, fact_id, status):
        self.writes.append("fact_status")
        for index, fact in enumerate(self.facts):
            if fact.id == fact_id:
                self.facts[index] = fact.model_copy(update={"status": status})
                return
        raise KeyError(fact_id)

    def get_evidence(self, evidence_id):
        for item in self.evidence:
            if item.id == evidence_id:
                return item
        raise KeyError(evidence_id)

    def list_evidence(self, task_id, kind=None):
        return [e for e in self.evidence if e.task_id == task_id and (kind is None or kind == e.kind)]

    def add_evidence(self, artifact):
        self.writes.append("evidence")
        self.evidence.append(artifact)
        return artifact

    def record_inbound(self, event):
        existing = next((e for e in self.inbound.values() if (e.source, e.external_id) == (event.source, event.external_id)), None)
        if existing is not None:
            return existing, False
        self.writes.append("inbound")
        self.inbound[event.id] = event
        return event, True

    def get_inbound(self, inbound_id):
        return self.inbound[inbound_id]

    def get_latest_approval(self, task_id):
        approvals = self.list_approvals(task_id)
        return approvals[-1] if approvals else None

    def list_approvals(self, task_id):
        return [a for a in self.approvals if a.task_id == task_id]

    def create_approval_request(self, proposal):
        self.writes.append("approval_request")
        return self.approve(proposal, status="requested")

    def decide_approval(self, approval_id, decision, approver):
        from app.core.schemas import utcnow
        for index, approval in enumerate(self.approvals):
            if approval.id == approval_id:
                if approval.status != "requested" or decision not in {"approved", "rejected"}:
                    raise ValueError("Approval is not pending or decision is invalid")
                decided = approval.model_copy(update={"status": decision, "approver": approver, "decided_at": utcnow()})
                self.approvals[index] = decided
                self.writes.append("approval_decision")
                return decided
        raise KeyError(approval_id)

    def invalidate_approvals(self, task_id, reason):
        invalidated = []
        for index, approval in enumerate(self.approvals):
            if approval.task_id == task_id and approval.status in {"requested", "approved"}:
                item = approval.model_copy(update={"status": "invalidated", "invalidated_reason": reason})
                self.approvals[index] = item
                invalidated.append(item)
                self.writes.append("approval_invalidated")
        return invalidated

    def save_verification(self, result):
        self.writes.append("verification")
        self.verifications.append(result)
        return result

    def latest_verification(self, task_id):
        return next((v for v in reversed(self.verifications) if v.task_id == task_id), None)

    def source(self, text="provider reply", source_id=None):
        from app.core.schemas import EvidenceArtifact, new_id, utcnow
        artifact = EvidenceArtifact(id=source_id or new_id("evd"), task_id=self.task.id, kind="message_in",
            source="fixture_messaging", extracted={"text": text}, is_fixture=True, captured_at=utcnow())
        self.evidence.append(artifact)
        return artifact.id

    def approve(self, proposal, status="approved"):
        from app.core.schemas import Approval, new_id, utcnow
        approval = Approval(id=new_id("apr"), task_id=self.task.id, proposal=proposal, proposal_hash=proposal.compute_hash(),
                            status=status, requested_at=utcnow(), decided_at=utcnow() if status == "approved" else None)
        self.approvals.append(approval)
        return approval

    def seed_provider(self, provider_id="provider_a", charge=12000, slots=None):
        from app.context.facts import ingest_fact
        values = {"service_supported": True, "base_charge_cents": charge, "visit_charge_cents": charge,
                  "fee_scope": "diagnostic_visit_including_travel", "repair_cost_known": False,
                  "slots_offered": slots if slots is not None else [{"start": "2026-10-20T22:00:00Z", "end": "2026-10-20T23:00:00Z"}],
                  "cancellation_terms": "Free cancellation with 24 hours notice."}
        source = self.source()
        for field, value in values.items():
            ingest_fact(self.task.id, f"{provider_id}.{field}", value, source_id=source)
        return source


@pytest.fixture
def memory_repo(monkeypatch):
    pytest.importorskip("app.core.schemas", reason="Victor's CP0 shared schemas have not landed")
    from app.core import repo
    fake = MemoryRepo()
    for name in dir(fake):
        if not name.startswith("_") and callable(getattr(fake, name)):
            monkeypatch.setattr(repo, name, getattr(fake, name), raising=False)
    monkeypatch.setenv("LLM_MODE", "fixture")
    return fake
