"""Shared fixtures: every test gets its own SQLite file + artifact dir."""
from __future__ import annotations

import os

# Offline by default: never reach paid/live sponsor APIs from the test suite. This must run
# before any app import — `browser_use` calls load_dotenv() on import, which would otherwise
# copy .env keys and live modes into os.environ (it never overrides values already set).
if not os.environ.get("RUN_LIVE"):
    os.environ.update({"MESSAGING_MODE": "fixture", "BROWSER_MODE": "fixture", "LLM_MODE": "fixture",
                       "SENTRY_DSN": ""})
    for _key in ("BROWSER_USE_API_KEY", "ANTHROPIC_API_KEY", "PHOTON_API_KEY", "PHOTON_PROJECT_ID",
                 "LIVE_PROVIDER_A_HANDLE", "LIVE_PROVIDER_B_HANDLE"):
        os.environ[_key] = ""

import pytest  # noqa: E402

from app.core import db, repo  # noqa: E402
from app.core.api.demo import resolve_seed  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.schemas import Task  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    settings = get_settings()
    url = f"sqlite:///{(tmp_path / 'orbit.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "artifact_dir", str(tmp_path / "artifacts"))
    db.init_db(url)
    yield url


@pytest.fixture
def task() -> Task:
    """The seeded demo task (fixture mode), in DRAFT."""
    return repo.create_task(resolve_seed("fixture"))
