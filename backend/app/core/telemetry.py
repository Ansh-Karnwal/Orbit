"""Owner: Victor. Optional Sentry error reporting. A no-op unless SENTRY_DSN is set.

Privacy: no local variables, no request bodies/headers/cookies/query strings, no user, and every
string is passed through logs.redact (phones, emails, keys); keys that carry message bodies or
handles are dropped outright. Only operational failures are reported (exceptions, retryable
errors) — business outcomes like a FAIL verdict or a declined approval are not errors."""
from __future__ import annotations

import logging
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from app.core.config import get_settings
from app.core.logs import redact
from app.core.schemas import PlanStep

SENSITIVE_KEYS = {
    "text", "body", "message_text", "handle", "sender_handle", "customer_contact",
    "customer_name", "phone", "email", "authorization", "cookie", "cookies", "headers",
    "data", "query_string", "env", "api_key", "x-api-key", "vars",
}
_enabled = False


def _walk(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[redacted]" if str(k).lower() in SENSITIVE_KEYS else _walk(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v) for v in value]
    if isinstance(value, str):
        return redact(value)
    return value


def scrub(event: dict, hint: dict | None = None) -> dict:
    """before_send: keep only method + path of the request; drop user; redact everything else."""
    req = event.get("request")
    if isinstance(req, dict):
        event["request"] = {k: req[k].split("?")[0] if k == "url" else req[k]
                            for k in ("method", "url") if k in req}
    event.pop("user", None)
    return _walk(event)


def scrub_breadcrumb(crumb: dict, hint: dict | None = None) -> dict:
    return _walk(crumb)


def init(dsn: str | None = None, *, transport: Any = None) -> bool:
    """Initialise Sentry if a DSN is configured. Returns whether reporting is enabled."""
    global _enabled
    dsn = get_settings().sentry_dsn if dsn is None else dsn
    if not dsn:
        _enabled = False
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=get_settings().orbit_mode,     # PII collection stays at its default: off
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=0.0,
        before_send=scrub,
        before_breadcrumb=scrub_breadcrumb,
        integrations=[LoggingIntegration(level=logging.INFO, event_level=None)],
        transport=transport,
    )
    _enabled = True
    return True


def shutdown() -> None:
    global _enabled
    if _enabled:
        sentry_sdk.flush(timeout=2)
        sentry_sdk.init()                    # inactive client (no DSN)
    _enabled = False


def _tags(scope, task_id: str, step: PlanStep | None, **extra: str) -> None:
    scope.set_tag("task_id", task_id)
    if step is not None:
        scope.set_tag("step_kind", step.kind.value)
        scope.set_tag("step_id", step.id)
        if step.provider_id:
            scope.set_tag("provider_id", step.provider_id)
    for k, v in extra.items():
        scope.set_tag(k, v)


def step_failed(task_id: str, step: PlanStep, error: str | None, *,
                exc: BaseException | None, retrying: bool) -> None:
    if not _enabled:
        return
    with sentry_sdk.new_scope() as scope:
        _tags(scope, task_id, step, retrying=str(retrying).lower(), attempt=str(step.attempts))
        scope.set_level("warning" if retrying else "error")
        scope.fingerprint = ["step-failed", step.kind.value, type(exc).__name__ if exc else "outcome"]
        if exc is not None:
            sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_message(f"{step.kind.value} failed: {error}")


def step_recovered(task_id: str, step: PlanStep) -> None:
    if not _enabled:
        return
    with sentry_sdk.new_scope() as scope:
        _tags(scope, task_id, step, attempt=str(step.attempts))
        scope.set_level("info")
        scope.fingerprint = ["step-recovered", step.kind.value]
        sentry_sdk.capture_message(f"{step.kind.value} recovered after {step.attempts} attempts")


def tick_failed(task_id: str, exc: BaseException) -> None:
    if not _enabled:
        return
    with sentry_sdk.new_scope() as scope:
        _tags(scope, task_id, None, component="worker")
        sentry_sdk.capture_exception(exc)
