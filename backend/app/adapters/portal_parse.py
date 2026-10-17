"""Owner: Ansh. Deterministic extraction from portal HTML (data-field / data-slot-* attributes).

This, not the browser agent's own summary, is the source of truth for slots and confirmations.
Stdlib only; tolerant of attribute order and whitespace.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Literal

from pydantic import ValidationError

from app.core.schemas import ConfirmationExtract, Slot

PageKind = Literal["confirmed", "received", "error", "review", "booking_form", "lookup", "unknown"]
CONFIRMATION_FIELDS = ("confirmation_id", "provider_id", "service", "slot_start", "slot_end",
                       "visit_charge_cents", "cancellation_terms", "reference")


class _PortalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.groups: list[dict[str, str]] = [{}]       # group 0 = fields outside any data-booking
        self.slots: list[dict[str, str]] = []
        self.error_code: str | None = None
        self.no_booking = False
        self.h1 = ""
        self._field: tuple[str, list[str]] | None = None   # field without data-value: collect text
        self._in_h1 = False
        self._slot_label: list[str] | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if "data-booking" in a:
            self.groups.append({})
        if "data-error" in a:
            self.error_code = a["data-error"] or "error"
        if "data-no-booking" in a:
            self.no_booking = True
        if "data-field" in a:
            if "data-value" in a:
                self.groups[-1].setdefault(a["data-field"], a["data-value"].strip())
            else:
                self._field = (a["data-field"], [])
        if tag == "input" and "data-slot-start" in a:
            self.slots.append({"start": a["data-slot-start"], "end": a.get("data-slot-end", ""),
                               "label": ""})
            self._slot_label = []
        if tag == "h1":
            self._in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        if self._field is not None and tag in ("dd", "p", "span", "div", "td"):
            name, parts = self._field
            self.groups[-1].setdefault(name, " ".join("".join(parts).split()))
            self._field = None
        if tag == "label" and self._slot_label is not None:
            self.slots[-1]["label"] = " ".join("".join(self._slot_label).split())
            self._slot_label = None
        if tag == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._field is not None:
            self._field[1].append(data)
        if self._slot_label is not None:
            self._slot_label.append(data)
        if self._in_h1:
            self.h1 += data


def _parse(html: str) -> _PortalParser:
    p = _PortalParser()
    p.feed(html)
    p.close()
    return p


def parse_slots(html: str) -> list[Slot]:
    out = []
    for s in _parse(html).slots:
        try:
            out.append(Slot(start=s["start"], end=s["end"], label=s["label"]))
        except ValidationError:
            continue
    return out


def page_fields(html: str) -> dict[str, str]:
    """data-field values outside any booking block (e.g. the review page summary)."""
    return _parse(html).groups[0]


def parse_bookings(html: str) -> list[dict[str, str]]:
    """Every booking block on the page that carries a confirmation id (confirmation or lookup)."""
    return [g for g in _parse(html).groups if g.get("confirmation_id")]


def to_extract(fields: dict[str, str]) -> ConfirmationExtract | None:
    if not all(fields.get(k) is not None for k in CONFIRMATION_FIELDS) or not fields["confirmation_id"]:
        return None
    try:
        return ConfirmationExtract(
            confirmation_id=fields["confirmation_id"], provider_id=fields["provider_id"],
            service=fields["service"], slot_start=fields["slot_start"],
            slot_end=fields["slot_end"], visit_charge_cents=int(fields["visit_charge_cents"]),
            cancellation_terms=fields["cancellation_terms"], orbit_ref=fields["reference"])
    except (ValidationError, ValueError):
        return None


def parse_confirmation(html: str) -> ConfirmationExtract | None:
    """The confirmation exactly as the page states it (a mismatch is returned as-is)."""
    bookings = parse_bookings(html)
    return to_extract(bookings[0]) if bookings else None


def page_kind(html: str) -> PageKind:
    p = _parse(html)
    heading = p.h1.strip().lower()
    if p.error_code:
        return "error"
    if heading == "booking confirmed":
        return "confirmed"
    if heading == "request received" or "we received your request" in "".join(p.text).lower():
        return "received"
    if heading == "review your booking":
        return "review"
    if heading == "find my booking":
        return "lookup"
    if heading == "book a visit":
        return "booking_form"
    return "unknown"


def error_code(html: str) -> str | None:
    return _parse(html).error_code
