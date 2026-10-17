"""Adapter test wiring: fake evidence layer, in-process portal, opt-in live markers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest

from app.core import evidence

from .fakes import NOW, PORTAL, FakeEvidence

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "portal"))
import portal_core  # noqa: E402

LIVE_MARKERS = {
    "live_browser_use": "real Browser Use run against a running portal (RUN_LIVE=1)",
    "live_photon": "real Photon send/receive with a consenting teammate (RUN_LIVE=1)",
}


def pytest_configure(config):
    for name, doc in LIVE_MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {doc}")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LIVE"):
        return
    skip = pytest.mark.skip(reason="live sponsor test; set RUN_LIVE=1 to run")
    for item in items:
        if any(item.get_closest_marker(m) for m in LIVE_MARKERS):
            item.add_marker(skip)


@pytest.fixture
def ev(monkeypatch) -> FakeEvidence:
    fake = FakeEvidence()
    monkeypatch.setattr(evidence, "save_evidence", fake.save_evidence)
    return fake


@pytest.fixture
def portal_app(tmp_path):
    return portal_core.create_app(tmp_path / "portal.db", now_fn=lambda: NOW)


@pytest.fixture
async def portal_client(portal_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=portal_app),
                                 base_url=PORTAL) as c:
        yield c
