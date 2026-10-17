"""Owner: Victor. Demo endpoints (§3.6). /demo/seed is live from CP0; the rest land in Phase 6."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.schemas import (Constraints, DemoInjectIn, Mode, PortalFaultIn, ProviderSpec,
                              TaskCreate, utcnow)

router = APIRouter(prefix="/demo")

SEED_PATH = Path(__file__).resolve().parents[4] / "demo" / "seed.json"
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class DemoResetIn(BaseModel):
    create_task: bool = False
    mode: Literal["fixture", "live"] = "fixture"


def _next_weekday(today: date, weekday: str) -> date:
    """Next occurrence strictly after today (if today matches, next week's)."""
    ahead = (_WEEKDAYS.index(weekday) - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def resolve_seed(mode: Mode = "fixture", now: datetime | None = None) -> TaskCreate:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    settings = get_settings()
    tz = ZoneInfo(seed["timezone"])
    day = _next_weekday((now or utcnow()).astimezone(tz).date(), seed["window"]["weekday"])

    def at(hhmm: str) -> datetime:
        local = datetime.combine(day, time.fromisoformat(hhmm), tzinfo=tz)
        return local.astimezone(ZoneInfo("UTC"))

    providers = []
    for p in seed["providers"]:
        live_handle = getattr(settings, p["live_handle_env"].lower(), "")
        if mode == "live" and live_handle:
            channel, handle = "imessage", live_handle
        else:
            channel, handle = "fixture", p["fixture_handle"]
        providers.append(ProviderSpec(
            id=p["id"], name=p["name"], channel=channel, handle=handle,
            portal_url=settings.portal_base_url.rstrip("/") + p["portal_path"],
        ))
    return TaskCreate(
        outcome_text=seed["outcome_text"],
        constraints=Constraints(
            service=seed["service"],
            window_start=at(seed["window"]["start_local"]),
            window_end=at(seed["window"]["end_local"]),
            timezone=seed["timezone"],
            max_visit_charge_cents=seed["max_visit_charge_cents"],
        ),
        providers=providers,
        mode=mode,
        source="demo_seed",
    )


@router.get("/seed", response_model=TaskCreate)
def get_seed() -> TaskCreate:
    return resolve_seed(get_settings().orbit_mode)


@router.post("/reset")
def reset(body: DemoResetIn) -> dict:
    raise HTTPException(status_code=501, detail="not implemented yet (Phase 6)")


@router.post("/inject-event")
async def inject_event(body: DemoInjectIn) -> dict:
    raise HTTPException(status_code=501, detail="not implemented yet (Phase 6)")


@router.post("/portal-fault")
async def portal_fault(body: PortalFaultIn) -> dict:
    raise HTTPException(status_code=501, detail="not implemented yet (Phase 6)")
