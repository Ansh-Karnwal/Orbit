"""Owner: Victor. FastAPI app wiring. Shared file — changes go through Victor."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters import photon_routes, registry
from app.core import worker
from app.core.api import demo, tasks
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 1: db.init_db(); Phase 7: recovery; Phase 4: worker + messaging subscription.
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
app.include_router(tasks.router)
app.include_router(demo.router)
if photon_routes.router is not None:
    app.include_router(photon_routes.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mode": get_settings().orbit_mode,
            "integrations": registry.integration_status()}
