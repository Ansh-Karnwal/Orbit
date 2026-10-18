"""Owner: Victor. One error envelope for every non-2xx response (roadmap F1):

    {"error": {"code", "message", "retryable", "field", "details"}, "detail": <legacy>}

`detail` keeps its old per-endpoint shape for one release so existing clients keep working
(422: list of {loc,msg,type}; 409 stale_proposal: {code,current_hash,reason}; else a string)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("orbit.api")

STATUS_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
                405: "method_not_allowed", 409: "conflict", 422: "invalid_request",
                501: "not_implemented", 502: "upstream_unavailable", 503: "unavailable"}


class OrbitError(Exception):
    def __init__(self, status: int, code: str, message: str, *, details: dict | None = None,
                 retryable: bool = False, field: str | None = None, legacy: Any = None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details, self.retryable, self.field, self.legacy = details or {}, retryable, field, legacy


def envelope(status: int, code: str, message: str, *, details: dict | None = None,
             retryable: bool = False, field: str | None = None, legacy: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=jsonable_encoder({
        "detail": message if legacy is None else legacy,
        "error": {"code": code, "message": message, "retryable": retryable, "field": field,
                  "details": details or {}}}))


def validation_error(fields: list[dict], code: str = "invalid_request",
                     message: str = "Some fields need attention.") -> JSONResponse:
    clean = [{"loc": list(f.get("loc", [])), "msg": f.get("msg", ""), "type": f.get("type", "value_error")}
             for f in fields]
    return envelope(422, code, message, details={"fields": clean}, legacy=clean,
                    field=".".join(str(x) for x in clean[0]["loc"][1:]) if clean else None)


def install(app: FastAPI) -> None:
    from app.core.answers import AnswerError
    from app.core.approvals import StaleProposal
    from app.core.repo import NotFound
    from app.core.state import IllegalTransition

    @app.exception_handler(OrbitError)
    async def _orbit(_: Request, e: OrbitError):
        return envelope(e.status, e.code, e.message, details=e.details, retryable=e.retryable,
                        field=e.field, legacy=e.legacy)

    @app.exception_handler(StaleProposal)
    async def _stale(_: Request, e: StaleProposal):
        return envelope(409, "stale_proposal", "Terms changed since you saw them.",
                        details={"current_hash": e.current_hash, "reason": e.reason},
                        legacy=e.detail())

    @app.exception_handler(AnswerError)
    async def _answer(_: Request, e: AnswerError):
        return envelope(e.status, e.code, e.message)

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, e: NotFound):
        return envelope(404, "not_found", str(e.args[0]) if e.args else "not found")

    @app.exception_handler(IllegalTransition)
    async def _illegal(_: Request, e: IllegalTransition):
        return envelope(409, "illegal_transition", str(e))

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, e: RequestValidationError):
        return validation_error(e.errors())

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        message = e.detail if isinstance(e.detail, str) else STATUS_CODES.get(e.status_code, "error")
        return envelope(e.status_code, STATUS_CODES.get(e.status_code, "error"), message,
                        legacy=e.detail)

    @app.exception_handler(Exception)
    async def _internal(_: Request, e: Exception):
        log.error("unhandled %s", type(e).__name__, exc_info=e)
        support_id = None
        try:
            import sentry_sdk
            support_id = sentry_sdk.last_event_id()
        except Exception:  # noqa: BLE001
            pass
        return envelope(500, "internal", "Something went wrong on Orbit's side.",
                        details={"support_id": support_id}, retryable=True)
