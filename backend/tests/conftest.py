"""Shared fixtures: every test gets its own SQLite file + artifact dir."""
from __future__ import annotations

import pytest

from app.core import db, repo
from app.core.api.demo import resolve_seed
from app.core.config import get_settings
from app.core.schemas import Task


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
