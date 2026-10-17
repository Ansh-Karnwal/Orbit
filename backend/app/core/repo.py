"""Owner: Victor. Sync repository — the only module that touches the DB.
Returns Pydantic models, never ORM rows. §3.5 functions are contract; the extra helpers below
them (tasks, steps, inbound processing, timeline reads, counters, pub/sub) are core-internal."""
from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from contextlib import contextmanager
from typing import Iterator, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, literal_column, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import db
from app.core.db import (ActionRow, ApprovalRow, Base, BudgetCounterRow, EvidenceRow, FactRow,
                         InboundRow, ProviderRow, StepRow, TaskRow, TimelineRow, UTCDateTime,
                         VerificationRow)
from app.core.schemas import (TERMINAL_STATUSES, Approval, ContextFact, EvidenceArtifact,
                              FactStatus, InboundEvent, PlanStep, Proposal, ProviderSpec, Task,
                              TaskCreate, TaskStatus, TimelineEvent, ToolAction,
                              VerificationResult, Verdict, new_id, utcnow)
from app.core.state import CompletionGateError, check_transition

M = TypeVar("M", bound=BaseModel)

ACTIVE_FACT_STATUSES = (FactStatus.CONFIRMED.value, FactStatus.PROPOSED.value)


class NotFound(KeyError):
    pass


# ---------------------------------------------------------------- plumbing
@contextmanager
def _tx() -> Iterator[Session]:
    """One transaction (BEGIN IMMEDIATE). Timeline events emitted inside are published to
    SSE subscribers only after the commit succeeds."""
    with db.session() as s:
        with s.begin():
            yield s
        events: list[TimelineEvent] = s.info.pop("events", [])
    for ev in events:
        _publish(ev)


def _values(model: BaseModel, row_cls: type[Base], **extra) -> dict:
    """Model -> column kwargs. DateTime columns get real datetimes; everything else JSON-safe."""
    py, js = model.model_dump(), model.model_dump(mode="json")
    out = {}
    for col in row_cls.__table__.columns:
        if col.key in py:
            out[col.key] = py[col.key] if isinstance(col.type, UTCDateTime) else js[col.key]
    out.update(extra)
    return out


def _to(model: type[M], row: Base) -> M:
    return model.model_validate(
        {c.key: getattr(row, c.key) for c in row.__table__.columns if c.key in model.model_fields})


def _get(s: Session, row_cls: type[Base], pk, what: str):
    row = s.get(row_cls, pk)
    if row is None:
        raise NotFound(f"{what} {pk!r} not found")
    return row


def _rowid_desc(row_cls: type[Base]):
    return literal_column(f"{row_cls.__tablename__}.rowid").desc()


# ---------------------------------------------------------------- pub/sub (SSE)
_subs: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = defaultdict(set)
_subs_lock = threading.Lock()


def subscribe(task_id: str) -> asyncio.Queue:
    """Call from async code. Returns a queue receiving TimelineEvents emitted after this call."""
    q: asyncio.Queue = asyncio.Queue()
    with _subs_lock:
        _subs[task_id].add((asyncio.get_running_loop(), q))
    return q


def unsubscribe(task_id: str, q: asyncio.Queue) -> None:
    with _subs_lock:
        _subs[task_id] = {(lp, qq) for lp, qq in _subs[task_id] if qq is not q}
        if not _subs[task_id]:
            del _subs[task_id]


def _publish(ev: TimelineEvent) -> None:
    with _subs_lock:
        targets = list(_subs.get(ev.task_id, ()))
    for loop, q in targets:
        try:
            loop.call_soon_threadsafe(q.put_nowait, ev)
        except RuntimeError:  # loop closed; subscriber is gone
            pass


# ---------------------------------------------------------------- timeline
def _emit(s: Session, task_id: str, type: str, message: str, data: dict | None = None) -> TimelineEvent:
    seq = (s.scalar(select(func.max(TimelineRow.seq)).where(TimelineRow.task_id == task_id)) or 0) + 1
    ev = TimelineEvent(id=new_id("tl"), task_id=task_id, seq=seq, type=type, message=message,
                       data=data or {}, at=utcnow())
    ev = TimelineEvent.model_validate(ev.model_dump(mode="json"))   # normalise data to JSON types
    s.add(TimelineRow(**_values(ev, TimelineRow)))
    s.flush()
    s.info.setdefault("events", []).append(ev)
    return ev


def emit(task_id: str, type: str, message: str, data: dict | None = None) -> TimelineEvent:
    with _tx() as s:
        return _emit(s, task_id, type, message, data)


def list_timeline(task_id: str, after_seq: int = 0, last: int | None = None) -> list[TimelineEvent]:
    """Ascending by seq. `last` keeps only the newest N."""
    with db.session() as s:
        q = select(TimelineRow).where(TimelineRow.task_id == task_id, TimelineRow.seq > after_seq)
        if last is not None:
            rows = s.scalars(q.order_by(TimelineRow.seq.desc()).limit(last)).all()[::-1]
        else:
            rows = s.scalars(q.order_by(TimelineRow.seq)).all()
        return [_to(TimelineEvent, r) for r in rows]


# ---------------------------------------------------------------- tasks & providers
def create_task(body: TaskCreate) -> Task:
    now = utcnow()
    task = Task(id=new_id("tsk"), outcome_text=body.outcome_text, constraints=body.constraints,
                limits=body.limits, mode=body.mode, status=TaskStatus.DRAFT, source=body.source,
                creao_ref=body.creao_ref, created_at=now, updated_at=now)
    with _tx() as s:
        s.add(TaskRow(**_values(task, TaskRow)))
        s.flush()
        for i, p in enumerate(body.providers):
            s.add(ProviderRow(**_values(p, ProviderRow, task_id=task.id, position=i)))
        s.add(BudgetCounterRow(task_id=task.id, llm_calls=0))
        _emit(s, task.id, "task.created", "Task created",
              {"mode": task.mode, "source": task.source,
               "provider_ids": [p.id for p in body.providers]})
    return task


def get_task(task_id: str) -> Task:
    with db.session() as s:
        return _to(Task, _get(s, TaskRow, task_id, "task"))


def list_tasks() -> list[Task]:
    with db.session() as s:
        rows = s.scalars(select(TaskRow).order_by(TaskRow.created_at.desc(), _rowid_desc(TaskRow)))
        return [_to(Task, r) for r in rows]


def list_active_tasks() -> list[Task]:
    terminal = [t.value for t in TERMINAL_STATUSES]
    with db.session() as s:
        rows = s.scalars(select(TaskRow).where(TaskRow.status.not_in(terminal))
                         .order_by(TaskRow.created_at))
        return [_to(Task, r) for r in rows]


def _check_completion_gate(s: Session, task_id: str) -> None:
    v = s.scalars(select(VerificationRow).where(VerificationRow.task_id == task_id)
                  .order_by(VerificationRow.created_at.desc(), _rowid_desc(VerificationRow))
                  .limit(1)).first()
    a = s.scalars(select(ApprovalRow).where(ApprovalRow.task_id == task_id)
                  .order_by(ApprovalRow.requested_at.desc(), _rowid_desc(ApprovalRow))
                  .limit(1)).first()
    if v is None or v.verdict != Verdict.PASS.value:
        raise CompletionGateError("completion requires a PASS verification")
    if a is None or a.status != "approved":
        raise CompletionGateError("completion requires a current approved approval")
    if v.approval_id != a.id:
        raise CompletionGateError("PASS verification refers to a different approval")


def set_status(task_id: str, status: TaskStatus, reason: str = "") -> Task:
    """Enforces the state machine and the completion gate; emits task.status_changed.
    Setting the current status again only updates the reason (no event)."""
    status = TaskStatus(status)
    with _tx() as s:
        row = _get(s, TaskRow, task_id, "task")
        current = TaskStatus(row.status)
        if current == status:
            if reason and reason != row.status_reason:
                row.status_reason, row.updated_at = reason, utcnow()
            return _to(Task, row)
        check_transition(current, status)
        if status == TaskStatus.COMPLETED:
            _check_completion_gate(s, task_id)
        row.status, row.status_reason, row.updated_at = status.value, reason, utcnow()
        _emit(s, task_id, "task.status_changed", f"{current.value} → {status.value}",
              {"from": current.value, "to": status.value, "reason": reason})
        return _to(Task, row)


def set_summary(task_id: str, summary: str) -> Task:
    with _tx() as s:
        row = _get(s, TaskRow, task_id, "task")
        row.summary, row.updated_at = summary, utcnow()
        return _to(Task, row)


def get_providers(task_id: str) -> list[ProviderSpec]:
    with db.session() as s:
        rows = s.scalars(select(ProviderRow).where(ProviderRow.task_id == task_id)
                         .order_by(ProviderRow.position))
        return [_to(ProviderSpec, r) for r in rows]


def get_provider(task_id: str, provider_id: str) -> ProviderSpec:
    with db.session() as s:
        return _to(ProviderSpec, _get(s, ProviderRow, (task_id, provider_id), "provider"))


def find_task_by_handle(handle: str) -> tuple[str, str] | None:
    terminal = [t.value for t in TERMINAL_STATUSES]
    with db.session() as s:
        row = s.execute(
            select(ProviderRow.task_id, ProviderRow.id)
            .join(TaskRow, TaskRow.id == ProviderRow.task_id)
            .where(ProviderRow.handle == handle, TaskRow.status.not_in(terminal))
            .order_by(TaskRow.created_at.desc()).limit(1)).first()
        return (row[0], row[1]) if row else None


# ---------------------------------------------------------------- facts
def list_facts(task_id: str, key_prefix: str | None = None,
               include_inactive: bool = False) -> list[ContextFact]:
    with db.session() as s:
        q = select(FactRow).where(FactRow.task_id == task_id)
        if key_prefix:
            q = q.where(FactRow.key.startswith(key_prefix, autoescape=True))
        if not include_inactive:
            q = q.where(FactRow.status.in_(ACTIVE_FACT_STATUSES))
        rows = s.scalars(q.order_by(FactRow.key, FactRow.version))
        return [_to(ContextFact, r) for r in rows]


def get_active_fact(task_id: str, key: str) -> ContextFact | None:
    with db.session() as s:
        row = s.scalars(select(FactRow)
                        .where(FactRow.task_id == task_id, FactRow.key == key,
                               FactRow.status.in_(ACTIVE_FACT_STATUSES))
                        .order_by(FactRow.version.desc()).limit(1)).first()
        return _to(ContextFact, row) if row else None


def insert_fact(fact: ContextFact) -> ContextFact:
    with _tx() as s:
        s.add(FactRow(**_values(fact, FactRow)))
    return fact


def set_fact_status(fact_id: str, status: FactStatus) -> None:
    with _tx() as s:
        _get(s, FactRow, fact_id, "fact").status = FactStatus(status).value


# ---------------------------------------------------------------- evidence
def add_evidence(ev: EvidenceArtifact) -> EvidenceArtifact:
    with _tx() as s:
        s.add(EvidenceRow(**_values(ev, EvidenceRow)))
    return ev


def list_evidence(task_id: str, kind: str | None = None) -> list[EvidenceArtifact]:
    with db.session() as s:
        q = select(EvidenceRow).where(EvidenceRow.task_id == task_id)
        if kind:
            q = q.where(EvidenceRow.kind == kind)
        rows = s.scalars(q.order_by(EvidenceRow.captured_at, literal_column("evidence.rowid")))
        return [_to(EvidenceArtifact, r) for r in rows]


def get_evidence(evidence_id: str) -> EvidenceArtifact:
    with db.session() as s:
        return _to(EvidenceArtifact, _get(s, EvidenceRow, evidence_id, "evidence"))


# ---------------------------------------------------------------- inbound
def record_inbound(ev: InboundEvent) -> tuple[InboundEvent, bool]:
    """Race-safe dedup on (source, external_id): insert; on IntegrityError return the existing row."""
    try:
        with _tx() as s:
            s.add(InboundRow(**_values(ev, InboundRow)))
        return ev, True
    except IntegrityError:
        with db.session() as s:
            row = s.scalars(select(InboundRow).where(InboundRow.source == ev.source,
                                                     InboundRow.external_id == ev.external_id)).one()
            return _to(InboundEvent, row), False


def list_unprocessed_inbound(task_id: str) -> list[InboundEvent]:
    with db.session() as s:
        rows = s.scalars(select(InboundRow)
                         .where(InboundRow.task_id == task_id, InboundRow.processed.is_(False))
                         .order_by(InboundRow.received_at, literal_column("inbound_events.rowid")))
        return [_to(InboundEvent, r) for r in rows]


def list_inbound(task_id: str, provider_id: str | None = None) -> list[InboundEvent]:
    with db.session() as s:
        q = select(InboundRow).where(InboundRow.task_id == task_id)
        if provider_id:
            q = q.where(InboundRow.provider_id == provider_id)
        rows = s.scalars(q.order_by(InboundRow.received_at, literal_column("inbound_events.rowid")))
        return [_to(InboundEvent, r) for r in rows]


def mark_inbound_processed(inbound_id: str) -> None:
    with _tx() as s:
        _get(s, InboundRow, inbound_id, "inbound event").processed = True


# ---------------------------------------------------------------- approvals
def create_approval_request(proposal: Proposal) -> Approval:
    a = Approval(id=new_id("apr"), task_id=proposal.task_id, proposal=proposal,
                 proposal_hash=proposal.compute_hash(), status="requested", requested_at=utcnow())
    with _tx() as s:
        s.add(ApprovalRow(**_values(a, ApprovalRow)))
    return a


def get_approval(approval_id: str) -> Approval:
    with db.session() as s:
        return _to(Approval, _get(s, ApprovalRow, approval_id, "approval"))


def decide_approval(approval_id: str, decision: str, approver: str) -> Approval:
    if decision not in ("approved", "rejected"):
        raise ValueError(f"invalid decision {decision!r}")
    with _tx() as s:
        row = _get(s, ApprovalRow, approval_id, "approval")
        if row.status != "requested":
            raise ValueError(f"approval {approval_id} is {row.status}, not requested")
        row.status, row.approver, row.decided_at = decision, approver, utcnow()
        return _to(Approval, row)


def get_latest_approval(task_id: str) -> Approval | None:
    with db.session() as s:
        row = s.scalars(select(ApprovalRow).where(ApprovalRow.task_id == task_id)
                        .order_by(ApprovalRow.requested_at.desc(), _rowid_desc(ApprovalRow))
                        .limit(1)).first()
        return _to(Approval, row) if row else None


def list_approvals(task_id: str) -> list[Approval]:
    with db.session() as s:
        rows = s.scalars(select(ApprovalRow).where(ApprovalRow.task_id == task_id)
                         .order_by(ApprovalRow.requested_at, literal_column("approvals.rowid")))
        return [_to(Approval, r) for r in rows]


def invalidate_approvals(task_id: str, reason: str) -> list[Approval]:
    out: list[Approval] = []
    with _tx() as s:
        rows = s.scalars(select(ApprovalRow).where(ApprovalRow.task_id == task_id,
                                                   ApprovalRow.status.in_(("requested", "approved"))))
        for row in rows:
            row.status, row.invalidated_reason, row.decided_at = "invalidated", reason, utcnow()
            a = _to(Approval, row)
            out.append(a)
            _emit(s, task_id, "approval.invalidated", f"Approval invalidated: {reason}",
                  {"approval_id": a.id, "provider_id": a.proposal.provider_id, "reason": reason})
    return out


# ---------------------------------------------------------------- verification
def save_verification(v: VerificationResult) -> VerificationResult:
    with _tx() as s:
        s.add(VerificationRow(**_values(v, VerificationRow)))
    return v


def latest_verification(task_id: str) -> VerificationResult | None:
    with db.session() as s:
        row = s.scalars(select(VerificationRow).where(VerificationRow.task_id == task_id)
                        .order_by(VerificationRow.created_at.desc(), _rowid_desc(VerificationRow))
                        .limit(1)).first()
        return _to(VerificationResult, row) if row else None


# ---------------------------------------------------------------- tool actions
def get_action_by_key(idempotency_key: str) -> ToolAction | None:
    with db.session() as s:
        row = s.scalars(select(ActionRow).where(ActionRow.idempotency_key == idempotency_key)).first()
        return _to(ToolAction, row) if row else None


def save_action(a: ToolAction) -> ToolAction:
    """Insert or update by id. A second action with an existing idempotency_key raises IntegrityError."""
    with _tx() as s:
        s.merge(ActionRow(**_values(a, ActionRow)))
    return a


def list_actions(task_id: str, status: str | None = None) -> list[ToolAction]:
    with db.session() as s:
        q = select(ActionRow).where(ActionRow.task_id == task_id)
        if status:
            q = q.where(ActionRow.status == status)
        rows = s.scalars(q.order_by(ActionRow.started_at, literal_column("actions.rowid")))
        return [_to(ToolAction, r) for r in rows]


def count_actions(task_id: str) -> int:
    with db.session() as s:
        return s.scalar(select(func.count()).select_from(ActionRow)
                        .where(ActionRow.task_id == task_id)) or 0


# ---------------------------------------------------------------- plan steps
def save_steps(steps: list[PlanStep], events: list[tuple[str, str, dict]] | None = None,
               task_id: str | None = None) -> list[PlanStep]:
    """Insert or update by id, plus optional (type, message, data) timeline events for `task_id`
    (default: the steps' task) — all in one transaction, so a plan revision is never half-applied."""
    with _tx() as s:
        for st in steps:
            s.merge(StepRow(**_values(st, StepRow)))
        s.flush()
        if events:
            tid = task_id or steps[0].task_id
            for type_, message, data in events:
                _emit(s, tid, type_, message, data)
    return steps


def save_step(step: PlanStep) -> PlanStep:
    return save_steps([step])[0]


def get_step(step_id: str) -> PlanStep:
    with db.session() as s:
        return _to(PlanStep, _get(s, StepRow, step_id, "step"))


def list_steps(task_id: str) -> list[PlanStep]:
    with db.session() as s:
        rows = s.scalars(select(StepRow).where(StepRow.task_id == task_id)
                         .order_by(StepRow.created_at, literal_column("steps.rowid")))
        return [_to(PlanStep, r) for r in rows]


# ---------------------------------------------------------------- budgets
def incr_llm_calls(task_id: str) -> int:
    with _tx() as s:
        s.execute(update(BudgetCounterRow).where(BudgetCounterRow.task_id == task_id)
                  .values(llm_calls=BudgetCounterRow.llm_calls + 1))
        return s.scalar(select(BudgetCounterRow.llm_calls)
                        .where(BudgetCounterRow.task_id == task_id)) or 0


def get_llm_calls(task_id: str) -> int:
    with db.session() as s:
        return s.scalar(select(BudgetCounterRow.llm_calls)
                        .where(BudgetCounterRow.task_id == task_id)) or 0
