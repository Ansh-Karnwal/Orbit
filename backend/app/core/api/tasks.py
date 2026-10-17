"""Owner: Victor. Task, approval, evidence, SSE and artifact routes (§3.6)."""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.core import approvals, repo, worker
from app.core.api.stream import resolve_start, stream_timeline
from app.core.api.views import build_view
from app.core.config import get_settings
from app.core.schemas import (TERMINAL_STATUSES, Approval, ApprovalDecisionIn, EvidenceArtifact,
                              Task, TaskCreate, TaskStatus, TaskView, utcnow)

router = APIRouter()

PING_INTERVAL_S = 15


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
    if not body.providers:
        err(["providers"], "at least one provider is required")
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
    return errors


# ---------------------------------------------------------------- tasks
@router.post("/tasks", response_model=TaskView, status_code=201)
def create_task(body: TaskCreate):
    errors = validate_intake(body)
    if errors:
        return JSONResponse(status_code=422, content={"detail": errors})
    task = repo.create_task(body)
    worker.wake(task.id)
    return build_view(task.id)


@router.get("/tasks", response_model=list[Task])
def list_tasks() -> list[Task]:
    return repo.list_tasks()


@router.get("/tasks/{task_id}", response_model=TaskView)
def get_task_view(task_id: str) -> TaskView:
    return build_view(task_id)


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request, after_seq: int = 0,
                      last_event_id: str | None = Header(default=None)):
    repo.get_task(task_id)                                   # 404 before opening a stream
    start = resolve_start(after_seq, last_event_id)

    async def frames():
        async for ev in stream_timeline(task_id, start):
            if await request.is_disconnected():
                return
            yield ServerSentEvent(data=ev.model_dump_json(), event="timeline", id=str(ev.seq))

    return EventSourceResponse(frames(), ping=PING_INTERVAL_S,
                               ping_message_factory=lambda: ServerSentEvent(event="ping", data=""))


@router.post("/tasks/{task_id}/approvals", response_model=Approval)
def post_approval(task_id: str, body: ApprovalDecisionIn):
    try:
        return approvals.decide(task_id, body)
    except approvals.StaleProposal as e:
        return JSONResponse(status_code=409, content={"detail": e.detail()})


@router.post("/tasks/{task_id}/cancel", response_model=Task)
def cancel_task(task_id: str) -> Task:
    task = repo.get_task(task_id)
    if task.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"task is already {task.status.value}")
    repo.invalidate_approvals(task_id, "task cancelled")
    task = repo.set_status(task_id, TaskStatus.CANCELLED, "cancelled by user")
    worker.wake(task_id)
    return task


@router.get("/tasks/{task_id}/evidence", response_model=list[EvidenceArtifact])
def list_task_evidence(task_id: str) -> list[EvidenceArtifact]:
    repo.get_task(task_id)
    return repo.list_evidence(task_id)


# ---------------------------------------------------------------- artifacts
@router.get("/artifacts/{evidence_id}")
def get_artifact(evidence_id: str):
    ev = repo.get_evidence(evidence_id)
    if not ev.uri:
        raise HTTPException(status_code=404, detail="evidence has no file")
    root = Path(get_settings().artifact_dir).resolve()
    path = (root / ev.uri).resolve()
    if not path.is_relative_to(root) or not path.is_file():   # path-traversal guard
        raise HTTPException(status_code=404, detail="artifact file not found")
    return FileResponse(path, media_type=ev.mime_type or "application/octet-stream")
