"""Owner: Victor. FastAPI app wiring. Shared file — changes go through Victor."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters import photon_routes, registry
from app.core import auth, db, errors, recovery, telemetry, worker
from app.core.api import demo, tasks
from app.core.config import get_settings
from app.core.logs import setup_logging

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
    # Deployed origins come from env (comma-separated); localhost:3000 is the dev frontend.
    allow_origins=[o.strip() for o in os.environ.get("ORBIT_CORS_ORIGINS",
                                                     "http://localhost:3000").split(",") if o.strip()],
    allow_credentials=True,            # the sign-in cookie
    allow_methods=["*"],
    allow_headers=["*"],
)
errors.install(app)                    # one error envelope for every non-2xx response

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(demo.router)
if photon_routes.router is not None:
    app.include_router(photon_routes.router)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {"ok": True, "mode": s.orbit_mode, "auth_mode": s.orbit_auth_mode,
            "text_approvals": s.orbit_text_approvals,
            "integrations": registry.integration_status()}
