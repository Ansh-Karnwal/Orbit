"""Owner: Victor. Task, approval, answer, evidence, SSE, artifact and service routes (§3.6).
Every task route is scoped to the signed-in user (auth.current_user); errors use errors.envelope."""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.context.domain import load_pack
from app.core import answers, approvals, repo, worker
from app.core.api.stream import resolve_start, stream_timeline
from app.core.api.views import build_view
from app.core.auth import current_user, owned_task
from app.core.config import get_settings
from app.core.errors import OrbitError, validation_error
from app.core.schemas import (TERMINAL_STATUSES, AnswerIn, Approval, ApprovalDecisionIn,
                              EvidenceArtifact, ServiceInfo, Task, TaskCreate, TaskStatus,
                              TaskView, UserInfo, utcnow)

router = APIRouter()

PING_INTERVAL_S = 15
MAX_PROVIDERS = 10


def service_catalog() -> list[ServiceInfo]:
    pack = load_pack()
    return [ServiceInfo(id=s.id, label=s.label, pack=f"{pack.name}/{pack.version}",
                        description=s.description) for s in pack.services]


# ---------------------------------------------------------------- intake validation (A1)
def validate_intake(body: TaskCreate) -> list[dict]:
    """Readable, field-addressed errors in FastAPI's 422 shape. Empty list = valid."""
    errors: list[dict] = []

    def err(loc: list, msg: str) -> None:
        errors.append({"loc": ["body", *loc], "msg": msg, "type": "value_error"})

    c = body.constraints
    if c.window_start.tzinfo is None or c.window_end.tzinfo is None:
        err(["constraints", "window_start"],
            "window_start and window_end must include a UTC offset (e.g. '2026-10-20T21:00:00Z')")
    else:
        if c.window_end <= c.window_start:
            err(["constraints", "window_end"], "window_end must be after window_start")
        if c.window_start <= utcnow():
            err(["constraints", "window_start"], "the time window must be in the future")
    try:
        ZoneInfo(c.timezone)
    except Exception:
        err(["constraints", "timezone"], f"unknown timezone {c.timezone!r} (use an IANA name "
                                         "like 'America/Los_Angeles')")
    if c.max_visit_charge_cents <= 0:
        err(["constraints", "max_visit_charge_cents"],
            "max_visit_charge_cents must be a positive whole number of cents")
    services = [s.id for s in service_catalog()]
    if services and c.service not in services:
        err(["constraints", "service"],
            f"unknown service {c.service!r} (supported: {', '.join(services)})")
    if not body.providers:
        err(["providers"], "at least one provider is required")
    if len(body.providers) > MAX_PROVIDERS:
        err(["providers"], f"at most {MAX_PROVIDERS} providers per task")
    ids = [p.id for p in body.providers]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        err(["providers"], f"duplicate provider ids: {', '.join(dups)}")
    for i, p in enumerate(body.providers):
        if not p.id.strip():
            err(["providers", i, "id"], "provider id must not be empty")
        if not p.handle.strip():
            err(["providers", i, "handle"], "provider handle must not be empty")
        elif body.mode == "live" and (p.channel == "fixture" or p.handle.startswith("fixture:")):
            err(["providers", i, "handle"],
                "live mode needs a real messaging handle, not a fixture handle")
    if body.user_contact is not None:
        contact = body.user_contact.strip()
        if not contact:
            err(["user_contact"], "leave user_contact out, or give a handle Orbit can text")
        elif contact in {p.handle for p in body.providers}:
            err(["user_contact"], "your contact can't be one of the providers' handles")
        elif body.mode == "live" and contact.startswith("fixture:"):
            err(["user_contact"], "live mode needs your real handle, not a fixture one")
    return errors


# ---------------------------------------------------------------- services
@router.get("/services", response_model=list[ServiceInfo])
def list_services() -> list[ServiceInfo]:
    return service_catalog()


# ---------------------------------------------------------------- tasks
@router.post("/tasks", response_model=TaskView, status_code=201)
def create_task(body: TaskCreate, user: UserInfo = Depends(current_user)):
    errors = validate_intake(body)
    if errors:
        return validation_error(errors, code="invalid_intake",
                                message="Some details of this request need attention.")
    task = repo.create_task(body, owner_id=user.user_id)
    worker.wake(task.id)
    return build_view(task.id)


@router.get("/tasks", response_model=list[Task])
def list_tasks(service: str | None = None, status: TaskStatus | None = None,
               user: UserInfo = Depends(current_user)) -> list[Task]:
    return repo.list_tasks(owner_id=user.user_id, service=service,
                           status=status.value if status else None)


@router.get("/tasks/{task_id}", response_model=TaskView)
def get_task_view(task_id: str, user: UserInfo = Depends(current_user)) -> TaskView:
    owned_task(task_id, user)
    return build_view(task_id)


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request, after_seq: int = 0,
                      last_event_id: str | None = Header(default=None),
                      user: UserInfo = Depends(current_user)):
    owned_task(task_id, user)                                # 404 before opening a stream
    start = resolve_start(after_seq, last_event_id)

    async def frames():
        async for ev in stream_timeline(task_id, start):
            if await request.is_disconnected():
                return
            yield ServerSentEvent(data=ev.model_dump_json(), event="timeline", id=str(ev.seq))

    return EventSourceResponse(frames(), ping=PING_INTERVAL_S,
                               ping_message_factory=lambda: ServerSentEvent(event="ping", data=""))


@router.post("/tasks/{task_id}/approvals", response_model=Approval)
def post_approval(task_id: str, body: ApprovalDecisionIn,
                  user: UserInfo = Depends(current_user)) -> Approval:
    owned_task(task_id, user)
    return approvals.decide(task_id, body, approver=user.user_id)   # StaleProposal -> 409


@router.post("/tasks/{task_id}/answers", response_model=Task)
def post_answer(task_id: str, body: AnswerIn, user: UserInfo = Depends(current_user)) -> Task:
    owned_task(task_id, user)
    return answers.answer(task_id, body, user.user_id)              # AnswerError -> 409/422


@router.post("/tasks/{task_id}/cancel", response_model=Task)
def cancel_task(task_id: str, user: UserInfo = Depends(current_user)) -> Task:
    task = owned_task(task_id, user)
    if task.status in TERMINAL_STATUSES:
        raise OrbitError(409, "already_terminal", f"task is already {task.status.value}")
    repo.invalidate_approvals(task_id, "task cancelled")
    task = repo.set_status(task_id, TaskStatus.CANCELLED, "cancelled by user")
    worker.wake(task_id)
    return task


@router.get("/tasks/{task_id}/evidence", response_model=list[EvidenceArtifact])
def list_task_evidence(task_id: str, user: UserInfo = Depends(current_user)) -> list[EvidenceArtifact]:
    owned_task(task_id, user)
    return repo.list_evidence(task_id)


@router.get("/tasks/{task_id}/sources/{source_id}", response_model=EvidenceArtifact)
def get_task_source(task_id: str, source_id: str,
                    user: UserInfo = Depends(current_user)) -> EvidenceArtifact:
    """Resolve a fact's artifact or inbound-event reference within this task only."""
    owned_task(task_id, user)
    evidence = repo.list_evidence(task_id)
    direct = next((e for e in evidence if e.id == source_id), None)
    if direct is not None:
        return direct
    inbound = next((e for e in repo.list_inbound(task_id) if e.id == source_id), None)
    if inbound is not None:
        match = next((e for e in evidence if e.kind == "message_in"
                      and e.extracted.get("external_id") == inbound.external_id
                      and e.extracted.get("provider_id") == inbound.provider_id
                      and e.source == {"photon": "photon", "fixture": "fixture_messaging",
                                       "demo": "demo"}[inbound.source]), None)
        if match is not None:
            return match
    raise OrbitError(404, "not_found", "The source message is unavailable for this task.")


# ---------------------------------------------------------------- artifacts
@router.get("/artifacts/{evidence_id}")
def get_artifact(evidence_id: str, user: UserInfo = Depends(current_user)):
    ev = repo.get_evidence(evidence_id)
    owned_task(ev.task_id, user)
    if not ev.uri:
        raise OrbitError(404, "not_found", "evidence has no file")
    root = Path(get_settings().artifact_dir).resolve()
    path = (root / ev.uri).resolve()
    if not path.is_relative_to(root) or not path.is_file():   # path-traversal guard
        raise OrbitError(404, "not_found", "artifact file not found")
    return FileResponse(path, media_type=ev.mime_type or "application/octet-stream")
