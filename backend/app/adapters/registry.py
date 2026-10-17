"""Owner: Ansh. Adapter selection by env (MESSAGING_MODE / BROWSER_MODE) and integration status.

A live adapter that can't initialise is replaced by a Blocked adapter that fails every call with
the reason — never a silent fixture fallback that looks live.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Awaitable, Callable

from app.adapters.base import AdapterUnavailable, BrowserAdapter, MessagingAdapter
from app.adapters.fixture_browser import FixtureBrowserAdapter
from app.adapters.fixture_messaging import FixtureMessagingAdapter
from app.core.config import get_settings
from app.core.schemas import (AvailabilityResult, BookingRequest, BookingResult, InboundEvent,
                              Mode, ProviderSpec, SendResult)

log = logging.getLogger(__name__)

# Explicit overrides (tests, demos): when set, messaging()/browser() return these as-is.
_messaging: MessagingAdapter | None = None
_browser: BrowserAdapter | None = None

_fixture_messaging: FixtureMessagingAdapter | None = None
_fixture_browser: FixtureBrowserAdapter | None = None
_live_messaging: MessagingAdapter | None = None
_live_browser: BrowserAdapter | None = None


class BlockedMessagingAdapter:
    is_fixture = False

    def __init__(self, name: str, reason: str) -> None:
        self.name, self.reason = name, reason

    async def send(self, task_id: str, provider: ProviderSpec, text: str,
                   idempotency_key: str) -> SendResult:
        return SendResult(status="failed", error=f"{self.name} blocked: {self.reason}")

    async def start(self, on_inbound: Callable[[InboundEvent], Awaitable[None]]) -> None:
        log.warning("%s blocked: %s", self.name, self.reason)

    async def stop(self) -> None:
        return None


class BlockedBrowserAdapter:
    is_fixture = False

    def __init__(self, name: str, reason: str) -> None:
        self.name, self.reason = name, reason

    async def read_availability(self, task_id: str, provider: ProviderSpec, day_local: date,
                                tz: str) -> AvailabilityResult:
        return AvailabilityResult(slots=[], error=f"{self.name} blocked: {self.reason}")

    async def submit_booking(self, req: BookingRequest) -> BookingResult:
        return BookingResult(status="failed", error=f"{self.name} blocked: {self.reason}")

    async def find_booking(self, task_id: str, provider: ProviderSpec,
                           orbit_ref: str) -> BookingResult | None:
        # "couldn't look" is never "not found": ambiguous stops callers from resubmitting
        return BookingResult(status="ambiguous", error=f"{self.name} blocked: {self.reason}")


# ---------------------------------------------------------------- constructors
def _fixture_msg() -> FixtureMessagingAdapter:
    global _fixture_messaging
    if _fixture_messaging is None:
        _fixture_messaging = FixtureMessagingAdapter()
    return _fixture_messaging


def _fixture_br() -> FixtureBrowserAdapter:
    global _fixture_browser
    if _fixture_browser is None:
        _fixture_browser = FixtureBrowserAdapter()
    return _fixture_browser


def _live_msg() -> MessagingAdapter:
    global _live_messaging
    if _live_messaging is None:
        try:
            from app.adapters.photon import PhotonMessagingAdapter
            _live_messaging = PhotonMessagingAdapter()
        except AdapterUnavailable as e:
            _live_messaging = BlockedMessagingAdapter("photon", str(e))
        except Exception as e:                      # SDK import errors etc.
            _live_messaging = BlockedMessagingAdapter("photon", f"init failed: {e!r}")
    return _live_messaging


def _live_br() -> BrowserAdapter:
    global _live_browser
    if _live_browser is None:
        try:
            from app.adapters.browser_use_adapter import BrowserUseAdapter
            _live_browser = BrowserUseAdapter()
        except AdapterUnavailable as e:
            _live_browser = BlockedBrowserAdapter("browser_use", str(e))
        except Exception as e:
            _live_browser = BlockedBrowserAdapter("browser_use", f"init failed: {e!r}")
    return _live_browser


# ---------------------------------------------------------------- contract §3.5
def messaging() -> MessagingAdapter:
    """Adapter chosen by MESSAGING_MODE (fixture | photon)."""
    if _messaging is not None:
        return _messaging
    return _live_msg() if get_settings().messaging_mode == "photon" else _fixture_msg()


def browser() -> BrowserAdapter:
    """Adapter chosen by BROWSER_MODE (fixture | browser_use)."""
    if _browser is not None:
        return _browser
    return _live_br() if get_settings().browser_mode == "browser_use" else _fixture_br()


def integration_status() -> dict[str, str]:
    settings = get_settings()
    return {
        "photon": _status(_live_msg) if settings.messaging_mode == "photon" else "fixture",
        "browser_use": _status(_live_br) if settings.browser_mode == "browser_use" else "fixture",
        "creao": "fixture",                         # Adithya: switch to "manual-handoff" when ready
        "llm": _llm_status(),
    }


# ---------------------------------------------------------------- extras (not in the contract)
def messaging_for(mode: Mode) -> MessagingAdapter:
    """Per-task selection: fixture tasks always use fixtures; live tasks use the env-selected live
    adapter, or a Blocked one — a live task never silently runs on fixtures."""
    if _messaging is not None:
        return _messaging
    return _fixture_msg() if mode == "fixture" else _live_msg()


def browser_for(mode: Mode) -> BrowserAdapter:
    if _browser is not None:
        return _browser
    return _fixture_br() if mode == "fixture" else _live_br()


async def start_all(on_inbound: Callable[[InboundEvent], Awaitable[None]]) -> None:
    """Subscribe inbound on every messaging adapter that may be used (fixture + env live)."""
    if _messaging is not None:
        await _messaging.start(on_inbound)
        return
    await _fixture_msg().start(on_inbound)
    if get_settings().messaging_mode == "photon":
        await _live_msg().start(on_inbound)


async def stop_all() -> None:
    for adapter in (_fixture_messaging, _live_messaging):
        if adapter is not None:
            await adapter.stop()


def reset() -> None:
    """Drop cached adapters (tests, /demo/reset)."""
    global _fixture_messaging, _fixture_browser, _live_messaging, _live_browser
    if _fixture_messaging is not None:
        _fixture_messaging.reset()
    _fixture_messaging = _fixture_browser = _live_messaging = _live_browser = None


def _status(make: Callable[[], object]) -> str:
    adapter = make()
    reason = getattr(adapter, "reason", None)
    return f"blocked: {reason}" if reason else "live"


def _llm_status() -> str:
    try:
        from app.llm import client
        status = getattr(client, "status", None)
        return status() if callable(status) else "fixture"
    except Exception as e:
        return f"blocked: {e!r}"
