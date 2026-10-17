"""Owner: Victor. JSON-lines logging with redaction. Message bodies are never logged at INFO;
phone numbers, emails and key-like tokens are masked defensively anyway."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

_REDACTIONS = [
    (re.compile(r"\+\d{10,15}\b"), "[phone]"),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[phone]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b(sk|pk|bu|key|tok)[-_][A-Za-z0-9_-]{8,}"), "[secret]"),
    (re.compile(r"(?i)(authorization|api[-_]?key|x-api-key)(['\"]?\s*[:=]\s*)\S+"), r"\1\2[secret]"),
]
_EXTRA_KEYS = ("task_id", "step_id", "step_kind", "provider_id")


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat().replace("+00:00", "Z"),
               "level": record.levelname, "logger": record.name,
               "msg": redact(record.getMessage())}
        for k in _EXTRA_KEYS:
            if hasattr(record, k):
                out[k] = getattr(record, k)
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, default=str)


def setup_logging() -> None:
    """Idempotent: attaches one JSON handler to the `orbit` logger tree."""
    logger = logging.getLogger("orbit")
    if any(getattr(h, "_orbit", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._orbit = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    logger.propagate = False
