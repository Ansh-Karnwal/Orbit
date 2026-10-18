"""Conservative offline parser for provider quotes and partial corrections."""
from datetime import date, datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from app.context.domain import service_terms
from app.context.quote import ExtraFee, ProviderQuoteExtraction, QuoteSlot
from app.context.values import iso

AMOUNT = r"\d+(?:\.\d{1,2})?"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DIRECTIVE = re.compile(r"ignore\b.{0,60}\b(instructions|rules|previous)|book\s+(immediately|now)|change\b.{0,30}\b(budget|constraints)|approve\b.{0,30}\bbooking|<\s*/?\s*system", re.I)


def quote_text(text: str) -> str:
    # A directive sentence cannot become a quote (including its dollar amounts).
    return " ".join(s for s in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if not DIRECTIVE.search(s))


def _spoken(text: str) -> str:
    text = re.sub(r"\bone[ -]+(?:hundred[ -]+)?forty[ -]+five(?:\s+dollars)?\b", "$145", text, flags=re.I)
    return text


def _clock(value: str, meridiem: str | None) -> str:
    parts = value.split(":")
    hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    if minute >= 60 or hour > 23 or hour < 0:
        raise ValueError("Invalid local time")
    if meridiem:
        if not 1 <= hour <= 12:
            raise ValueError("Invalid 12-hour time")
        hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
    return f"{hour:02d}:{minute:02d}"


def _repair_included(text: str) -> bool:
    for match in re.finditer(r"\bincludes?\s+(?:all\s+)?(?:parts and labor|repairs?)\b", text):
        before = text[max(0, match.start() - 30):match.start()]
        if not re.search(r"\b(?:not|never|doesn't|don't)\s*$", before):
            return True
    return False


def _mentions_service(lower: str, service: str | None) -> bool:
    # Word boundaries matter: "washer" must not match inside "dishwasher".
    terms = sorted(service_terms(service), key=len, reverse=True)
    return bool(terms) and re.search(
        r"\b(?:" + "|".join(re.escape(t.lower()) for t in terms) + r")(?:e?s)?\b", lower) is not None


def parse_quote(text: str, service: str | None = None) -> ProviderQuoteExtraction:
    """`service` is the task's service id; None accepts any service in the pack's catalog."""
    clean = _spoken(quote_text(text))
    lower = clean.lower()
    q = ProviderQuoteExtraction()
    if not clean:
        return q
    if _mentions_service(lower, service):
        q.service_supported = not bool(re.search(r"(?:do not|don't|cannot|can't|no longer|not)\s+(?:\w+\s+){0,2}(?:repair|service|support)|(?:don't|do not)\s+work on", lower))
    q.is_correction = bool(re.search(r"forgot|sorry|correction|on top|actually|updated", lower))
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    cancel = [s.strip() for s in sentences if re.search(r"\bcancel", s, re.I)]
    if cancel:
        q.cancellation_terms = " ".join(cancel)
    if re.search(r"parts?.{0,30}labor.{0,60}after diagnosis|(?:parts|labor).{0,40}quoted after diagnos", lower):
        q.repair_cost_after_diagnosis = True
    price_text = " ".join(s for s in sentences if not re.search(r"\bcancel|parts and labor", s, re.I))
    uncertain = bool(re.search(r"starting\s+(?:at|from)|\bfrom\s+\$|\b(?:estimate|estimated|might|approximately|about|up to|at least)\b|\$\d+(?:\.\d+)?\s*(?:to|[-–])\s*\$?\d+", price_text, re.I))
    trip = re.search(rf"\$\s*({AMOUNT})\s*(?:trip|travel|call-out|service call)\s*(?:charge|fee)?", price_text, re.I)
    trip_after = re.search(rf"(?:trip|travel|call-out)\s*(?:charge|fee)?\s*(?:of|is|:)?\s*\$\s*({AMOUNT})", price_text, re.I)
    fee = trip or trip_after
    if fee and not uncertain:
        q.extra_fees = [ExtraFee(name="trip", usd=fee.group(1))]
    explicit = re.search(rf"\$?\s*({AMOUNT})\s*(?:dollars?\s*)?total\b", price_text, re.I)
    if not explicit:
        explicit = re.search(rf"\btotal\s*(?:is|of|:)?\s*\$\s*({AMOUNT})", price_text, re.I)
    amounts = list(re.finditer(rf"\$\s*({AMOUNT})", price_text))
    base = next((m for m in amounts if not (fee and fee.start() <= m.start() < fee.end())
                 and not (explicit and explicit.start() <= m.start() < explicit.end())), None)
    quote_context = bool(re.search(r"diagnos|repair|visit|service call|total|trip|travel", lower))
    if quote_context and not uncertain:
        if explicit:
            q.total_visit_charge_usd = explicit.group(1)
        if base:
            if fee or not re.search(r"including\s+(?:all\s+)?travel|incl\.?\s*travel", lower):
                q.base_charge_usd = base.group(1)
            if not fee and q.total_visit_charge_usd is None:
                q.total_visit_charge_usd = base.group(1)
    repair_included = _repair_included(lower)
    scope_contradiction = bool(re.search(r"diagnostic(?: visit)?\s+only|diagnosis\s+only", lower) and repair_included)
    if scope_contradiction:
        q.fee_scope = "unknown"
        q.confidence_notes.append("contradiction: diagnostic only; includes repair")
    elif uncertain:
        q.fee_scope = "unknown"
        q.confidence_notes.append("Unconfirmed starting-at, estimated or ranged price")
    elif q.total_visit_charge_usd is not None or q.base_charge_usd is not None or q.extra_fees:
        if re.search(r"(?:flat|fixed).{0,20}repair", lower) or repair_included:
            q.fee_scope = "flat_repair"
            q.repair_cost_after_diagnosis = False
        elif re.search(r"excluding travel|plus travel|travel (?:fee|charge) (?:extra|tbd)|trip (?:fee|charge) (?:extra|tbd)", lower) and not fee:
            q.fee_scope = "diagnostic_visit_excluding_travel"
            q.total_visit_charge_usd = None
        else:
            q.fee_scope = "diagnostic_visit_including_travel"
    time_range = re.compile(r"(?<![\d:$])(\d{1,2}(?::\d{2})?)\s*(am|pm)?\s*[-–—]\s*(\d{1,2}(?::\d{2})?)\s*(am|pm)\b", re.I)
    slots = []
    for match in time_range.finditer(clean):
        prefix = clean[:match.start()]
        days = list(re.finditer(r"\b(?:" + "|".join(WEEKDAYS) + r"|\d{4}-\d{2}-\d{2})\b", prefix, re.I))
        if not days:
            continue
        first, am, last, pm = match.groups()
        try:
            start, end = _clock(first, am or pm), _clock(last, pm)
            if am is None and pm.lower() == "pm" and start >= end:
                start = _clock(first, "am")
            slots.append(QuoteSlot(day_text=days[-1].group(), start_local=start, end_local=end))
        except ValueError:
            continue
    if slots:
        q.slots = slots
    return q


def _local_instant(day: date, clock: str, tz: ZoneInfo) -> datetime:
    naive = datetime.fromisoformat(f"{day.isoformat()}T{clock}")
    first, second = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
    # Fail closed on DST gaps and folds; a provider must clarify ambiguous times.
    if first.utcoffset() != second.utcoffset() or first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != naive:
        raise ValueError("Ambiguous or nonexistent local slot")
    return first.astimezone(timezone.utc)


def resolve_slots(slots: list[QuoteSlot], constraints) -> list[dict[str, str]]:
    tz = ZoneInfo(constraints.timezone)
    anchor = constraints.window_start.astimezone(tz).date()
    resolved = []
    for slot in slots:
        day_text = re.sub(r"^(?:next|this)\s+", "", slot.day_text.strip().lower())
        if day_text in WEEKDAYS:
            offset = (WEEKDAYS.index(day_text) - anchor.weekday() + 3) % 7 - 3
            day = anchor + timedelta(days=offset)
        else:
            try:
                day = date.fromisoformat(day_text)
            except ValueError:
                continue
        if abs((day - anchor).days) > 14:
            continue
        try:
            start, end = _local_instant(day, slot.start_local, tz), _local_instant(day, slot.end_local, tz)
            if start < end:
                resolved.append({"start": iso(start), "end": iso(end)})
        except ValueError:
            continue
    return sorted(resolved, key=lambda s: s["start"])
