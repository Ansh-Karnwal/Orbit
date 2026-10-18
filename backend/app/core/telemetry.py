"""Sentry errors, workflow traces and structured logs. Optional without SENTRY_DSN.

Privacy: no local variables, no request bodies/headers/cookies/query strings, no user, and every
string is passed through logs.redact (phones, emails, keys); keys that carry message bodies or
handles are dropped outright. Only operational failures are reported (exceptions, retryable
errors) — business outcomes like a FAIL verdict or a declined approval are not errors."""
from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
log = logging.getLogger("orbit.observability")

# Operational metadata only. Never forward arbitrary executor results or provider replies.
ATTRIBUTES = {
    "event", "task_id", "step_id", "step_kind", "provider_id", "attempt", "mode",
    "duration_ms", "outcome", "retrying", "error_type", "verdict", "status",
    "offered_count", "portal_count", "matching_count", "within_window_count", "demo_run_id",
    "facts_changed", "decision", "reason_code", "fact_count", "evidence_count", "timeline_count",
}
LOG_SDK_ATTRIBUTES = {
    "logger.name", "sentry.origin", "sentry.environment", "sentry.release",
    "sentry.sdk.name", "sentry.sdk.version", "sentry.message.template",
}
SPAN_ATTRIBUTES = ATTRIBUTES | {
    "db.system", "db.name", "db.operation", "db.operation.name", "db.collection.name",
    "http.method", "http.request.method", "http.status_code", "http.response.status_code",
    "http.route", "server.address", "server.port", "thread.id", "thread.name",
}


def _url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return "[invalid url]"
    return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))


def _safe_string(value: str) -> str:
    return redact(re.sub(r"https?://[^\s\"'<>]+", lambda m: _url(m[0]), value))


def _attributes(values: dict, allowed=ATTRIBUTES) -> dict:
    return {k: _safe_string(v) if isinstance(v, str) else v
            for k, v in values.items()
            if k in allowed and isinstance(v, (str, int, float, bool))}


def _walk(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[redacted]" if str(k).lower() in SENSITIVE_KEYS else _walk(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v) for v in value]
    if isinstance(value, str):
        return _safe_string(value)
    return value


def scrub(event: dict, hint: dict | None = None) -> dict:
    """before_send: keep only method + path of the request; drop user; redact everything else."""
    req = event.get("request")
    if isinstance(req, dict):
        event["request"] = {k: _url(req[k]) if k == "url" else req[k]
                            for k in ("method", "url") if k in req}
    event.pop("user", None)
    return _walk(event)


def scrub_breadcrumb(crumb: dict, hint: dict | None = None) -> dict:
    return _walk(crumb)


def scrub_transaction(event: dict, hint: dict | None = None) -> dict:
    """Keep timing/SQL shapes and operational span attributes, never query parameters or bodies."""
    spans = event.pop("spans", [])
    trace = event.get("contexts", {}).get("trace", {})
    data = _attributes(trace.pop("data", {}), SPAN_ATTRIBUTES)
    result = scrub(event, hint)
    if trace:
        result["contexts"]["trace"]["data"] = data
    result["spans"] = []
    for span in spans:
        data = _attributes(span.pop("data", {}), SPAN_ATTRIBUTES)
        cleaned = _walk(span)
        cleaned["data"] = data
        result["spans"].append(cleaned)
    return result


def scrub_log(item: dict, hint: dict | None = None) -> dict | None:
    attributes = item.get("attributes", {})
    logger = attributes.get("logger.name", "")
    if logger != "orbit" and not logger.startswith("orbit."):
        return None
    item["body"] = _safe_string(item["body"])
    item["attributes"] = _attributes(attributes, ATTRIBUTES | LOG_SDK_ATTRIBUTES)
    return item


def _sample_trace(context: dict) -> float:
    path = context.get("asgi_scope", {}).get("path", "")
    if path == "/health" or path.endswith("/events"):
        return 0.0
    return get_settings().sentry_traces_sample_rate


def init(dsn: str | None = None, *, transport: Any = None) -> bool:
    """Enable errors, Tracing and Logs together. Returns whether reporting is configured."""
    global _enabled
    dsn = get_settings().sentry_dsn if dsn is None else dsn
    if not dsn:
        shutdown()
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=get_settings().sentry_environment,
        release=get_settings().sentry_release or None,
        data_collection={"user_info": False, "cookies": {"mode": "off"},
                         "http_headers": {"request": {"mode": "off"}}, "url_query_params": {"mode": "off"},
                         "http_bodies": [], "gen_ai": {"inputs": False, "outputs": False},
                         "stack_frame_variables": False, "database_query_data": False},
        include_local_variables=False,
        max_request_body_size="never",
        traces_sampler=_sample_trace,
        trace_propagation_targets=[re.escape(get_settings().portal_base_url.rstrip("/")) + r"(?:/|$)"],
        before_send=scrub,
        before_send_transaction=scrub_transaction,
        before_send_log=scrub_log,
        before_breadcrumb=scrub_breadcrumb,
        integrations=[LoggingIntegration(level=logging.INFO, event_level=None,
                                         sentry_logs_level=logging.INFO, capture_sentry_logs=True)],
        transport=transport,
    )
    _enabled = True
    return True


def record(event: str, task_id: str, *, level: int = logging.INFO, **attributes) -> None:
    log.log(level, event, extra=_attributes({"event": event, "task_id": task_id, **attributes}))


@contextmanager
def operation(op: str, name: str, **attributes):
    if not _enabled:
        yield None
        return
    with sentry_sdk.new_scope() as scope:
        transaction = scope.transaction
        if transaction is not None:
            for key in ("task_id", "mode"):
                if key in attributes:
                    transaction.set_tag(key, attributes[key])
        for key, value in _attributes(attributes).items():
            scope.set_tag(key, value)
        with sentry_sdk.start_span(op=op, name=name) as span:
            for key, value in _attributes(attributes).items():
                span.set_data(key, value)
            yield span


@contextmanager
def workflow(task_id: str):
    if not _enabled:
        yield None
        return
    with sentry_sdk.isolation_scope() as scope:
        scope.set_tag("task_id", task_id)
        with sentry_sdk.start_transaction(op="orbit.workflow", name="orbit.workflow.tick") as span:
            span.set_data("task_id", task_id)
            yield span


def status() -> dict:
    return {"configured": _enabled, "logs": _enabled,
            "tracing": _enabled and get_settings().sentry_traces_sample_rate > 0,
            "environment": get_settings().sentry_environment}


def shutdown() -> None:
    global _enabled
    if _enabled:
        sentry_sdk.flush(timeout=2)
        sentry_sdk.init(dsn="")              # inactive even when SENTRY_DSN is exported
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
