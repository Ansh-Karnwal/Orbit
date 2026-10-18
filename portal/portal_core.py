"""Owner: Ansh. Mock provider booking portal (FastAPI + Jinja2).

Two fake small-business booking sites that Orbit's browser agent books on, plus a JSON API for the
fixture adapter and an admin API for fault injection. Fault modes change what the *response* shows;
the stored booking is always the real one, so lookup/reconciliation sees the truth.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import string
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

import yaml
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
UTC = timezone.utc
FaultMode = Literal["none", "timeout_after_submit", "mismatch", "no_confirmation", "down"]
DEFAULT_TIMEOUT_DELAY_S = float(os.environ.get("PORTAL_TIMEOUT_DELAY_S", "90"))
MISMATCH_SHIFT = timedelta(hours=3)
MISMATCH_CHARGE_CENTS = 16500


# ---------------------------------------------------------------- helpers
def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return dt.astimezone(UTC)


def money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def local_time_label(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%I:%M %p").lstrip("0")


def slot_label(start: datetime, end: datetime, tz: ZoneInfo) -> str:
    return f"{local_time_label(start, tz)} – {local_time_label(end, tz)} PT"


def local_datetime_label(dt: datetime, tz: ZoneInfo) -> str:
    loc = dt.astimezone(tz)
    return f"{loc.strftime('%A, %B')} {loc.day}, {loc.year} at {local_time_label(dt, tz)} {loc.tzname()}"


def new_confirmation_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "BK-" + "".join(secrets.choice(alphabet) for _ in range(4))


# ---------------------------------------------------------------- catalogue
@dataclass(frozen=True)
class Catalogue:
    tz: ZoneInfo
    horizon: int
    providers: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> "Catalogue":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(tz=ZoneInfo(raw["timezone"]), horizon=int(raw["booking_horizon_weekdays"]),
                   providers=raw["providers"])

    def provider(self, pid: str) -> dict[str, Any]:
        if pid not in self.providers:
            raise HTTPException(404, f"unknown provider {pid}")
        return self.providers[pid]

    def service(self, pid: str, service_id: str) -> dict[str, Any] | None:
        return next((s for s in self.provider(pid)["services"] if s["id"] == service_id), None)


# ---------------------------------------------------------------- storage
class Store:
    """Tiny SQLite store: bookings + the current fault mode."""

    def __init__(self, path: Path) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS bookings (
                confirmation_id TEXT PRIMARY KEY, provider_id TEXT NOT NULL, service TEXT NOT NULL,
                slot_start TEXT NOT NULL, slot_end TEXT NOT NULL, visit_charge_cents INTEGER NOT NULL,
                cancellation_terms TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '',
                customer_name TEXT NOT NULL, customer_contact TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                demo_run_id TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(bookings)")}
        if "demo_run_id" not in columns:
            self._db.execute("ALTER TABLE bookings ADD COLUMN demo_run_id TEXT NOT NULL DEFAULT ''")
        self._db.commit()

    def fault(self) -> tuple[FaultMode, float]:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key='fault'").fetchone()
        if row is None:
            return "none", DEFAULT_TIMEOUT_DELAY_S
        data = json.loads(row["value"])
        return data["mode"], float(data["delay_s"])

    def set_fault(self, mode: FaultMode, delay_s: float) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO settings VALUES ('fault', ?)",
                             (json.dumps({"mode": mode, "delay_s": delay_s}),))
            self._db.commit()

    def reset(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM bookings")
            self._db.execute("DELETE FROM settings")
            self._db.commit()

    def insert_booking(self, b: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO bookings (confirmation_id, provider_id, service, slot_start, slot_end,"
                " visit_charge_cents, cancellation_terms, reference, customer_name, customer_contact,"
                " notes, created_at, demo_run_id)"
                " VALUES (:confirmation_id, :provider_id, :service, :slot_start,"
                " :slot_end, :visit_charge_cents, :cancellation_terms, :reference, :customer_name,"
                " :customer_contact, :notes, :created_at, :demo_run_id)", b)
            self._db.commit()

    def bookings(self, provider_id: str | None = None, reference: str | None = None,
                 demo_run_id: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM bookings WHERE 1=1", []
        if provider_id is not None:
            sql, args = sql + " AND provider_id=?", args + [provider_id]
        if reference is not None:
            sql, args = sql + " AND reference=?", args + [reference]
        if demo_run_id is not None:
            sql, args = sql + " AND demo_run_id=?", args + [demo_run_id]
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY created_at", args).fetchall()
        return [dict(r) for r in rows]

    def booked_starts(self, provider_id: str, demo_run_id: str = "") -> set[str]:
        return {b["slot_start"] for b in self.bookings(provider_id, demo_run_id=demo_run_id)}


# ---------------------------------------------------------------- API models
class FaultIn(BaseModel):
    mode: FaultMode
    delay_s: float | None = None          # portal-only extra: sleep for timeout_after_submit


class BookIn(BaseModel):
    slot_start: str
    service: str
    customer_name: str
    customer_contact: str
    reference: str = ""
    notes: str = ""
    demo_run_id: str = ""             # fixture task ID; each run has fresh availability


class BookingError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---------------------------------------------------------------- app factory
def create_app(db_path: Path | str | None = None,
               now_fn: Callable[[], datetime] | None = None) -> FastAPI:
    cat = Catalogue.load(HERE / "providers.yaml")
    store = Store(Path(db_path or os.environ.get("PORTAL_DB_PATH", HERE / "portal.db")))
    now = now_fn or (lambda: datetime.now(UTC))
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.globals.update(money=money)
    app = FastAPI(title="Orbit mock provider portal")
    app.state.store = store

    # ------------------------------------------------ slots
    def booking_days() -> list[date]:
        day, days = now().astimezone(cat.tz).date(), []
        while len(days) < cat.horizon:
            if day.weekday() < 5:
                days.append(day)
            day += timedelta(days=1)
        return days

    def slots_for(pid: str, day: date, demo_run_id: str = "") -> list[dict[str, Any]]:
        prov = cat.provider(pid)
        if day not in booking_days():
            return []
        taken, current, out = store.booked_starts(pid, demo_run_id), now(), []
        for start_s, end_s in prov["daily_slots"]:
            start = datetime.combine(day, time.fromisoformat(start_s), tzinfo=cat.tz).astimezone(UTC)
            end = datetime.combine(day, time.fromisoformat(end_s), tzinfo=cat.tz).astimezone(UTC)
            if start <= current or iso_z(start) in taken:
                continue
            out.append({"start": iso_z(start), "end": iso_z(end),
                        "label": slot_label(start, end, cat.tz)})
        return out

    def find_slot(pid: str, slot_start: str, demo_run_id: str = "") -> dict[str, Any] | None:
        try:
            start = parse_utc(slot_start)
        except ValueError:
            return None
        day = start.astimezone(cat.tz).date()
        return next((s for s in slots_for(pid, day, demo_run_id) if s["start"] == iso_z(start)), None)

    # ------------------------------------------------ booking core
    def check_booking(pid: str, data: BookIn) -> tuple[dict, dict]:
        prov = cat.provider(pid)
        service = cat.service(pid, data.service)
        if service is None:
            raise BookingError(422, "unknown_service", "That service is not offered.")
        if not data.customer_name.strip() or not data.customer_contact.strip():
            raise BookingError(422, "missing_fields", "Name and contact are required.")
        slot = find_slot(pid, data.slot_start, data.demo_run_id)
        if slot is None:
            raise BookingError(409, "slot_unavailable",
                               "Sorry, that time is no longer available. Please choose another slot.")
        return prov, {"service": service, "slot": slot}

    def record_booking(pid: str, data: BookIn) -> dict[str, Any]:
        prov, chosen = check_booking(pid, data)
        booking = {
            "confirmation_id": new_confirmation_id(), "provider_id": pid,
            "service": chosen["service"]["id"], "slot_start": chosen["slot"]["start"],
            "slot_end": chosen["slot"]["end"],
            "visit_charge_cents": chosen["service"]["visit_charge_cents"],
            "cancellation_terms": prov["cancellation_terms"], "reference": data.reference.strip(),
            "customer_name": data.customer_name.strip(),
            "customer_contact": data.customer_contact.strip(), "notes": data.notes.strip(),
            "created_at": now().astimezone(UTC).isoformat(),
            "demo_run_id": data.demo_run_id,
        }
        store.insert_booking(booking)
        return booking

    def displayed(booking: dict[str, Any], mode: FaultMode) -> dict[str, Any]:
        """What the confirmation shows. `mismatch` alters the display only, never the record."""
        b = dict(booking)
        if mode == "mismatch":
            b["slot_start"] = iso_z(parse_utc(b["slot_start"]) + MISMATCH_SHIFT)
            b["slot_end"] = iso_z(parse_utc(b["slot_end"]) + MISMATCH_SHIFT)
            b["visit_charge_cents"] = MISMATCH_CHARGE_CENTS
        return b

    def view(b: dict[str, Any]) -> dict[str, Any]:
        """Template-friendly booking with visible local labels next to machine values."""
        prov = cat.provider(b["provider_id"])
        service = cat.service(b["provider_id"], b["service"]) or {"label": b["service"]}
        start, end = parse_utc(b["slot_start"]), parse_utc(b["slot_end"])
        return {**b, "provider_name": prov["name"], "service_label": service["label"],
                "slot_start_label": local_datetime_label(start, cat.tz),
                "slot_end_label": local_datetime_label(end, cat.tz),
                "visit_charge_label": money(b["visit_charge_cents"]),
                "fees": prov.get("fees", [])}

    async def apply_fault_before_response() -> FaultMode:
        mode, delay = store.fault()
        if mode == "timeout_after_submit":
            await asyncio.sleep(delay)
        return mode

    def booking_routes_down() -> bool:
        return store.fault()[0] == "down"

    def page(request: Request, name: str, status: int = 200, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx, status_code=status)

    def unavailable(request: Request) -> HTMLResponse:
        return page(request, "error.html", 503, title="Service unavailable",
                    message="Online booking is temporarily unavailable. Please try again later.",
                    code="service_unavailable", provider=None)

    # ------------------------------------------------ HTML routes
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return page(request, "index.html", providers=cat.providers)

    @app.get("/p/{pid}", response_class=HTMLResponse)
    def provider_page(request: Request, pid: str):
        return page(request, "provider.html", pid=pid, provider=cat.provider(pid))

    @app.get("/p/{pid}/book", response_class=HTMLResponse)
    def book_form(request: Request, pid: str, date_: str | None = Query(None, alias="date")):
        prov, days = cat.provider(pid), booking_days()
        try:
            day = date.fromisoformat(date_) if date_ else days[0]
        except ValueError:
            raise HTTPException(422, "date must be YYYY-MM-DD")
        return page(request, "book.html", pid=pid, provider=prov, day=day,
                    day_label=f"{day.strftime('%A, %B')} {day.day}", days=days,
                    slots=slots_for(pid, day))

    @app.post("/p/{pid}/review", response_class=HTMLResponse)
    def review(request: Request, pid: str, slot: str = Form(""), service: str = Form(""),
               customer_name: str = Form(""), customer_contact: str = Form(""),
               reference: str = Form(""), notes: str = Form("")):
        prov = cat.provider(pid)
        if booking_routes_down():
            return unavailable(request)
        data = BookIn(slot_start=slot, service=service, customer_name=customer_name,
                      customer_contact=customer_contact, reference=reference, notes=notes)
        try:
            _, chosen = check_booking(pid, data)
        except BookingError as e:
            return page(request, "error.html", e.status, title="We couldn't continue",
                        message=e.message, code=e.code, provider=prov, pid=pid)
        return page(request, "review.html", pid=pid, provider=prov, data=data,
                    service=chosen["service"], slot=chosen["slot"],
                    slot_label=local_datetime_label(parse_utc(chosen["slot"]["start"]), cat.tz)
                    + " – " + local_time_label(parse_utc(chosen["slot"]["end"]), cat.tz))

    @app.post("/p/{pid}/book", response_class=HTMLResponse)
    async def book_submit(request: Request, pid: str, slot: str = Form(""),
                          service: str = Form(""), customer_name: str = Form(""),
                          customer_contact: str = Form(""), reference: str = Form(""),
                          notes: str = Form("")):
        prov = cat.provider(pid)
        if booking_routes_down():
            return unavailable(request)
        data = BookIn(slot_start=slot, service=service, customer_name=customer_name,
                      customer_contact=customer_contact, reference=reference, notes=notes)
        try:
            booking = record_booking(pid, data)
        except BookingError as e:
            return page(request, "error.html", e.status, title="We couldn't book that",
                        message=e.message, code=e.code, provider=prov, pid=pid)
        mode = await apply_fault_before_response()
        if mode == "no_confirmation":
            return page(request, "received.html", pid=pid, provider=prov)
        return page(request, "confirmed.html", pid=pid, provider=prov,
                    b=view(displayed(booking, mode)))

    @app.get("/p/{pid}/lookup", response_class=HTMLResponse)
    def lookup(request: Request, pid: str, ref: str = ""):
        prov = cat.provider(pid)
        found = [view(b) for b in store.bookings(pid, ref.strip(), demo_run_id="")] if ref.strip() else []
        return page(request, "lookup.html", pid=pid, provider=prov, ref=ref, bookings=found)

    # ------------------------------------------------ JSON API
    @app.get("/api/p/{pid}")
    def api_provider(pid: str):
        return {"provider_id": pid, "timezone": str(cat.tz), **cat.provider(pid)}

    @app.get("/api/p/{pid}/slots")
    def api_slots(pid: str, date_: str = Query(..., alias="date"), demo_run_id: str = ""):
        cat.provider(pid)
        try:
            day = date.fromisoformat(date_)
        except ValueError:
            raise HTTPException(422, "date must be YYYY-MM-DD")
        return {"provider_id": pid, "date": day.isoformat(), "timezone": str(cat.tz),
                "slots": slots_for(pid, day, demo_run_id)}

    @app.post("/api/p/{pid}/book")
    async def api_book(pid: str, body: BookIn):
        cat.provider(pid)
        if booking_routes_down():
            return JSONResponse({"error": "service_unavailable"}, status_code=503)
        try:
            booking = record_booking(pid, body)
        except BookingError as e:
            return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)
        mode = await apply_fault_before_response()
        if mode == "no_confirmation":
            return JSONResponse({"status": "received",
                                 "message": "We received your request and will be in touch."},
                                status_code=202)
        return JSONResponse({"status": "confirmed", "booking": displayed(booking, mode)},
                            status_code=201)

    @app.get("/api/p/{pid}/bookings")
    def api_bookings(pid: str, ref: str, demo_run_id: str = ""):
        cat.provider(pid)
        return {"provider_id": pid, "reference": ref,
                "bookings": store.bookings(pid, ref.strip(), demo_run_id=demo_run_id)}

    # ------------------------------------------------ admin
    @app.post("/admin/fault")
    def admin_fault(body: FaultIn):
        delay = body.delay_s if body.delay_s is not None else DEFAULT_TIMEOUT_DELAY_S
        store.set_fault(body.mode, delay)
        return {"mode": body.mode, "delay_s": delay}

    @app.post("/admin/reset")
    def admin_reset():
        store.reset()
        return {"ok": True}

    @app.get("/admin/state")
    def admin_state():
        mode, delay = store.fault()
        return {"fault": {"mode": mode, "delay_s": delay}, "bookings": store.bookings()}

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/p/{pid}/", include_in_schema=False)
    def provider_slash(pid: str):
        return RedirectResponse(f"/p/{pid}")

    return app
