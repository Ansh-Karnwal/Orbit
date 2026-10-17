"""Owner: Karthik. Stub from CP0 — replace."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DomainPack(BaseModel):
    name: str
    version: str
    rules: list[str] = Field(default_factory=list)
    required_keys: list[str] = Field(default_factory=list)   # per-provider suffixes, e.g. "visit_charge_cents"


def load_pack(name: str = "home_repair", version: str = "v1") -> "DomainPack":
    # Stub: hard-coded; the real one parses context/packs/{name}/{version}.yaml.
    return DomainPack(
        name=name, version=version,
        rules=["Visit charge must include all mandatory fees (trip/travel).",
               "Parts and labor are unknown until diagnosis unless quoted."],
        required_keys=["visit_charge_cents", "cancellation_terms"],
    )
