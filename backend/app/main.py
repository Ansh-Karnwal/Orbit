"""Owner: Victor. FastAPI app wiring. Shared file — changes go through Victor."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters import photon_routes, registry
from app.core import db, recovery, telemetry, worker
from app.core.api import demo, tasks
from app.core.config import get_settings
from app.core.logs import setup_logging
from app.core.repo import NotFound
from app.core.state import IllegalTransition

setup_logging()
telemetry.init()                       # no-op without SENTRY_DSN; must precede FastAPI()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    recovery.recover()                 # before the worker: no tick sees half-finished work
    await worker.start()
    yield
    await worker.stop()


app = FastAPI(title="Orbit", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc.args[0]) if exc.args else "not found"})


@app.exception_handler(IllegalTransition)
async def _illegal(_: Request, exc: IllegalTransition) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app.include_router(tasks.router)
app.include_router(demo.router)
if photon_routes.router is not None:
    app.include_router(photon_routes.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mode": get_settings().orbit_mode,
            "integrations": registry.integration_status(), "observability": telemetry.status()}
