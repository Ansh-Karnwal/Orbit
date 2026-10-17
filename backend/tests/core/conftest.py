from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.adapters import registry
from app.verify import verifier
from tests.core.fakes import FakeMessaging, FakePortal, fake_verify


@dataclass
class Env:
    messaging: FakeMessaging
    portal: FakePortal


@pytest.fixture
def env(monkeypatch) -> Env:
    """Fake messaging + portal adapters and a deterministic verifier, wired into the registry."""
    e = Env(FakeMessaging(), FakePortal())
    monkeypatch.setattr(registry, "_messaging", e.messaging)
    monkeypatch.setattr(registry, "_browser", e.portal)
    monkeypatch.setattr(verifier, "verify", fake_verify)
    return e
