"""Registry: env selection, blocked status never reported as live, blocked adapters fail loudly."""
from __future__ import annotations

from datetime import date

import pytest

from app.adapters import registry
from app.adapters.base import AdapterUnavailable
from app.adapters.fixture_browser import FixtureBrowserAdapter
from app.adapters.fixture_messaging import FixtureMessagingAdapter
from app.core.config import Settings

from .fakes import booking_request, provider


@pytest.fixture
def settings(monkeypatch):
    import app.adapters.browser_use_adapter as bua
    import app.adapters.photon as photon

    def use(**kw):
        fake = lambda: Settings(_env_file=None, **kw)  # noqa: E731
        for mod in (registry, bua, photon):
            if hasattr(mod, "get_settings"):
                monkeypatch.setattr(mod, "get_settings", fake)
    registry.reset()
    yield use
    registry.reset()


def test_fixture_by_default(settings):
    settings()
    assert isinstance(registry.messaging(), FixtureMessagingAdapter)
    assert isinstance(registry.browser(), FixtureBrowserAdapter)
    status = registry.integration_status()
    assert status["photon"] == "fixture" and status["browser_use"] == "fixture"
    assert set(status) == {"photon", "browser_use", "creao", "llm"}


def test_live_modes_report_blocked_not_live(settings, monkeypatch):
    settings(messaging_mode="photon", browser_mode="browser_use")
    status = registry.integration_status()
    assert status["photon"].startswith("blocked: ")
    assert status["browser_use"].startswith("blocked: ")
    assert registry.messaging().is_fixture is False and registry.browser().is_fixture is False


def test_init_crash_is_blocked(settings, monkeypatch):
    import app.adapters.browser_use_adapter as bua

    class Exploding:
        def __init__(self):
            raise ImportError("no module named browser_use")
    monkeypatch.setattr(bua, "BrowserUseAdapter", Exploding)
    settings(browser_mode="browser_use")
    assert "init failed" in registry.integration_status()["browser_use"]


async def test_blocked_adapters_fail_every_call(settings):
    settings(messaging_mode="photon", browser_mode="browser_use")
    sent = await registry.messaging().send("tsk", provider(), "hi", "k")
    assert sent.status == "failed" and "photon blocked" in sent.error
    b = registry.browser()
    assert (await b.read_availability("tsk", provider(), date(2026, 10, 20), "UTC")).error
    assert (await b.submit_booking(booking_request())).status == "failed"
    assert (await b.find_booking("tsk", provider(), "ORB-x")).status == "ambiguous"


def test_per_task_mode_selection(settings):
    settings(messaging_mode="photon", browser_mode="browser_use")
    assert isinstance(registry.messaging_for("fixture"), FixtureMessagingAdapter)
    assert isinstance(registry.browser_for("fixture"), FixtureBrowserAdapter)
    assert registry.browser_for("live").is_fixture is False      # blocked, not a fixture fallback


def test_adapter_unavailable_is_exception():
    assert issubclass(AdapterUnavailable, Exception)
