"""Owner: Ansh. Stub from CP0 — replace. Always returns fixture adapters for now."""
from __future__ import annotations

from app.adapters.base import BrowserAdapter, MessagingAdapter
from app.adapters.fixture_browser import FixtureBrowserAdapter
from app.adapters.fixture_messaging import FixtureMessagingAdapter

_messaging: MessagingAdapter | None = None
_browser: BrowserAdapter | None = None


def messaging() -> MessagingAdapter:
    global _messaging
    if _messaging is None:
        _messaging = FixtureMessagingAdapter()
    return _messaging


def browser() -> BrowserAdapter:
    global _browser
    if _browser is None:
        _browser = FixtureBrowserAdapter()
    return _browser


def integration_status() -> dict[str, str]:
    return {"photon": "fixture", "browser_use": "fixture", "creao": "fixture", "llm": "fixture"}
