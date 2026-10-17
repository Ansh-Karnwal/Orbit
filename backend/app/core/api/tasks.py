"""Owner: Victor. Task, approval, evidence, SSE and artifact routes (§3.6).
Stub from CP0 — routes exist with contract shapes; Phase 5 implements bodies."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.schemas import (Approval, ApprovalDecisionIn, EvidenceArtifact, Task, TaskCreate,
                              TaskView)

router = APIRouter()


def _todo() -> None:
    raise HTTPException(status_code=501, detail="not implemented yet (CP0 skeleton)")


@router.post("/tasks", response_model=TaskView, status_code=201)
def create_task(body: TaskCreate) -> TaskView:
    _todo()


@router.get("/tasks", response_model=list[Task])
def list_tasks() -> list[Task]:
    _todo()


@router.get("/tasks/{task_id}", response_model=TaskView)
def get_task_view(task_id: str) -> TaskView:
    _todo()


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, after_seq: int = 0):
    _todo()


@router.post("/tasks/{task_id}/approvals", response_model=Approval)
def post_approval(task_id: str, body: ApprovalDecisionIn) -> Approval:
    _todo()


@router.post("/tasks/{task_id}/cancel", response_model=Task)
def cancel_task(task_id: str) -> Task:
    _todo()


@router.get("/tasks/{task_id}/evidence", response_model=list[EvidenceArtifact])
def list_task_evidence(task_id: str) -> list[EvidenceArtifact]:
    _todo()


@router.get("/artifacts/{evidence_id}")
def get_artifact(evidence_id: str):
    _todo()
