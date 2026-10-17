"""Append-only fact versions; the coordinator owns timeline events."""
from datetime import datetime

from app.core import repo
from app.core.schemas import ContextFact, Conflict, FactStatus, IngestResult, new_id, utcnow
from app.context.values import cents, instant, normalize_slots


def _normalize(key: str, value):
    field = key.rsplit(".", 1)[-1]
    if field.endswith("_cents"):
        return cents(value)
    if field in {"slots_offered", "portal_slots"}:
        return normalize_slots(value)
    if field == "extra_fees":
        return sorted([{"name": str(x["name"]).strip(), "cents": cents(x["cents"])} for x in value], key=lambda x: (x["name"], x["cents"]))
    if field in {"service_supported", "repair_cost_known", "no_reply"} and not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value.strip() if isinstance(value, str) else value


def _validate_source(task_id: str, source_id: str):
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("A fact requires a source_id")
    if source_id.startswith("inb_"):
        lookup = getattr(repo, "get_inbound", None)
        if lookup is None:  # CP0 has no inbound lookup; the contract permits this fallback.
            return
    elif source_id.startswith("evd_"):
        lookup = repo.get_evidence
    else:
        raise ValueError("Source must be an evidence or inbound id")
    try:
        source = lookup(source_id)
    except (KeyError, LookupError) as exc:
        raise ValueError("Source does not exist") from exc
    if source is None or source.task_id != task_id:
        raise ValueError("Source must belong to this task")


def ingest_fact(task_id: str, key: str, value, *, source_id: str, scope: str | None = None,
                currency: str | None = None, observed_at: datetime | None = None,
                valid_until: datetime | None = None,
                status: FactStatus = FactStatus.CONFIRMED) -> IngestResult:
    _validate_source(task_id, source_id)
    if status not in {FactStatus.CONFIRMED, FactStatus.PROPOSED}:
        raise ValueError("Only proposed or confirmed observations may be ingested")
    if not key or "." not in key:
        raise ValueError("A provider-scoped fact key is required")
    provider_id = key.split(".", 1)[0]
    repo.get_provider(task_id, provider_id)
    value = _normalize(key, value)
    observed = instant(observed_at or utcnow())
    expiry = instant(valid_until) if valid_until is not None else None
    if expiry is not None and expiry <= observed:
        raise ValueError("valid_until must follow observed_at")
    if key.endswith("_cents"):
        if currency not in (None, "USD"):
            raise ValueError("Only USD is supported")
        currency = "USD"
    old = repo.get_active_fact(task_id, key)
    if old is not None and old.value == value and old.status == status:
        return IngestResult(fact=old, changed=False)
    history = [f for f in repo.list_facts(task_id, include_inactive=True) if f.key == key]
    stale = old is not None and observed < instant(old.observed_at)
    fact = ContextFact(id=new_id("fct"), task_id=task_id, key=key, value=value, source_id=source_id,
                       scope=scope, currency=currency, observed_at=observed, valid_until=expiry,
                       status=FactStatus.REJECTED if stale else status,
                       version=max((f.version for f in history), default=0) + 1,
                       supersedes=old.id if old and not stale else None)
    fact = repo.insert_fact(fact)
    if stale:
        return IngestResult(fact=fact, conflicts=[Conflict(kind="contradiction", key=key, provider_id=provider_id,
                            old_value=old.value, new_value=value, detail="Older message ignored; current fact retained")])
    conflicts = []
    if old is not None:
        repo.set_fact_status(old.id, FactStatus.SUPERSEDED)
        old = old.model_copy(update={"status": FactStatus.SUPERSEDED})
        conflicts.append(Conflict(kind="value_changed", key=key, provider_id=provider_id,
                                  old_value=old.value, new_value=value, detail=f"{key} changed"))
    from app.context.conflicts import detect_conflicts
    conflicts.extend(c for c in detect_conflicts(task_id) if c.provider_id == provider_id)
    return IngestResult(fact=fact, superseded=old, conflicts=conflicts)
