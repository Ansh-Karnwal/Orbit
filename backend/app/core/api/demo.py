"""Owner: Victor. Demo endpoints (§3.6): seed, sandbox providers, reset, inject-event, portal-fault."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.context.domain import service_label
from app.core import db, repo, worker
from app.core.auth import current_user
from app.core.config import get_settings
from app.core.errors import OrbitError, validation_error
from app.core.inbound import handle_inbound
from app.core.schemas import (Constraints, DemoInjectIn, InboundEvent, Mode, PortalFaultIn,
                              ProviderSpec, TaskCreate, UserInfo, new_id, utcnow)

router = APIRouter(prefix="/demo")
log = logging.getLogger("orbit.demo")

BACKEND_DIR = Path(__file__).resolve().parents[3]
SEED_PATH = BACKEND_DIR.parent / "demo" / "seed.json"
PORTAL_TIMEOUT_S = 5.0
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class DemoResetIn(BaseModel):
    create_task: bool = False
    mode: Literal["fixture", "live"] = "fixture"


# ---------------------------------------------------------------- seed
def _next_weekday(today: date, weekday: str) -> date:
    """Next occurrence strictly after today (if today matches, next week's)."""
    ahead = (_WEEKDAYS.index(weekday) - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def _load_seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _spec(p: dict, mode: Mode) -> ProviderSpec:
    settings = get_settings()
    live_handle = getattr(settings, p.get("live_handle_env", "").lower(), "") \
        if p.get("live_handle_env") else ""
    if mode == "live" and live_handle:
        channel, handle = "imessage", live_handle
    else:
        channel, handle = "fixture", p["fixture_handle"]
    return ProviderSpec(id=p["id"], name=p["name"], channel=channel, handle=handle,
                        portal_url=settings.portal_base_url.rstrip("/") + p["portal_path"])


def sandbox_providers(mode: Mode = "fixture") -> list[ProviderSpec]:
    """Every provider the sandbox knows (canonical two + extras), for intake's add-provider."""
    seed = _load_seed()
    return [_spec(p, mode) for p in seed["providers"] + seed.get("extra_providers", [])]


def resolve_seed(mode: Mode = "fixture", now: datetime | None = None,
                 service: str | None = None, extra: bool = False) -> TaskCreate:
    """The canonical demo task (next Tuesday 2–5 pm LA, $150, Ace + Bayside). `service` swaps in
    another catalog service; `extra` adds the sandbox's extra providers (more than two)."""
    seed = _load_seed()
    tz = ZoneInfo(seed["timezone"])
    day = _next_weekday((now or utcnow()).astimezone(tz).date(), seed["window"]["weekday"])

    def at(hhmm: str) -> datetime:
        local = datetime.combine(day, time.fromisoformat(hhmm), tzinfo=tz)
        return local.astimezone(ZoneInfo("UTC"))

    service = service or seed["service"]
    outcome = seed.get("outcome_texts", {}).get(service) or seed["outcome_text"].replace(
        "dishwasher repair", service_label(service).lower())
    raw = seed["providers"] + (seed.get("extra_providers", []) if extra else [])
    return TaskCreate(
        outcome_text=outcome,
        constraints=Constraints(
            service=service,
            window_start=at(seed["window"]["start_local"]),
            window_end=at(seed["window"]["end_local"]),
            timezone=seed["timezone"],
            max_visit_charge_cents=seed["max_visit_charge_cents"],
        ),
        providers=[_spec(p, mode) for p in raw],
        mode=mode,
        source="demo_seed",
    )


@router.get("/seed", response_model=TaskCreate)
def get_seed(service: str | None = None, extra: bool = False) -> TaskCreate:
    return resolve_seed(get_settings().orbit_mode, service=service, extra=extra)


@router.get("/providers", response_model=list[ProviderSpec])
def get_sandbox_providers() -> list[ProviderSpec]:
    return sandbox_providers(get_settings().orbit_mode)


# ---------------------------------------------------------------- portal proxy
async def _portal_post(path: str, body: dict) -> dict:
    """POST to the mock provider portal. Raises httpx errors to the caller."""
    url = get_settings().portal_base_url.rstrip("/") + path
    async with httpx.AsyncClient(timeout=PORTAL_TIMEOUT_S) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()
        return r.json() if r.content else {}


# ---------------------------------------------------------------- reset
def _artifact_root() -> Path:
    """ARTIFACT_DIR, refusing locations a wipe must never touch (fs root, home, code tree)."""
    root = Path(get_settings().artifact_dir).resolve()
    if root.parent == root or root == Path.home().resolve() or BACKEND_DIR.is_relative_to(root):
        raise OrbitError(500, "unsafe_artifact_dir",
                         f"refusing to clear ARTIFACT_DIR={root} (unsafe location)")
    return root


def _clear_artifacts(root: Path) -> None:
    if not root.exists():
        return
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


@router.post("/reset")
async def reset(body: DemoResetIn, user: UserInfo = Depends(current_user)):
    if not get_settings().orbit_allow_reset:
        raise OrbitError(403, "reset_disabled", "reset disabled (set ORBIT_ALLOW_RESET=1)")
    seed = None
    if body.create_task:
        from app.core.api.tasks import validate_intake
        seed = resolve_seed(body.mode)
        errors = validate_intake(seed)
        if errors:
            return validation_error(errors, code="invalid_intake",
                                    message="The seeded task can't be created in this mode.")
    artifacts = _artifact_root()            # validate before anything destructive happens

    was_running = worker.is_running()
    if was_running:
        await worker.stop()                 # cancels in-flight ticks and pending fixture replies
    try:
        db.reset_db()
        _clear_artifacts(artifacts)
        try:
            await _portal_post("/admin/reset", {})
        except (httpx.HTTPError, ValueError) as e:
            log.warning("portal reset failed: %s", type(e).__name__)
        task_id = repo.create_task(seed, owner_id=user.user_id).id if seed is not None else None
    finally:
        if was_running:
            await worker.start()
    if task_id:
        worker.wake(task_id)
    log.info("demo reset (task created: %s)", bool(task_id))
    return {"task_id": task_id}


# ---------------------------------------------------------------- inject / fault
@router.post("/inject-event")
async def inject_event(body: DemoInjectIn) -> dict:
    repo.get_task(body.task_id)                               # 404s via NotFound handler
    repo.get_provider(body.task_id, body.provider_id)
    ev = InboundEvent(id=new_id("inb"), source="demo",
                      external_id=body.external_id or new_id("ext"), task_id=body.task_id,
                      provider_id=body.provider_id, text=body.text, received_at=utcnow())
    await handle_inbound(ev)
    stored = repo.get_inbound_by_external("demo", ev.external_id)
    return {"inbound_id": stored.id, "created": stored.id == ev.id}


@router.post("/portal-fault")
async def portal_fault(body: PortalFaultIn) -> dict:
    try:
        out = await _portal_post("/admin/fault", body.model_dump())
    except (httpx.HTTPError, ValueError) as e:
        raise OrbitError(502, "portal_unreachable",
                         f"portal unreachable at {get_settings().portal_base_url} "
                         f"({type(e).__name__})", retryable=True) from e
    return {"mode": out.get("mode", body.mode)}
