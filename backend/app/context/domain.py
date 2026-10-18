"""Versioned, executable domain knowledge. No database or network access."""
from functools import lru_cache
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field
import yaml


class Term(BaseModel):
    definition: str
    synonyms: list[str]


class Example(BaseModel):
    name: str
    message: str
    service: str | None = None          # parse as a reply for this service (None = any in catalog)
    expected: dict = Field(default_factory=dict)


class ServiceDef(BaseModel):
    id: str
    label: str
    description: str = ""
    synonyms: list[str]                 # words a provider uses for it; matched on word boundaries


class DomainPack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    version: str
    services: list[ServiceDef] = Field(default_factory=list)
    intake_fields: dict[str, str]
    terminology: dict[str, Term]
    fee_distinctions: list[str]
    required_facts_for_eligibility: dict[str, str]
    comparison_rules: list[str]
    provider_questions: list[str]
    approval_boundaries: dict[str, list[str]]
    verification_predicates: dict[str, str]
    examples: list[Example]
    message_templates: dict[str, str]


@lru_cache(maxsize=16)
def load_pack(name: str = "home_repair", version: str = "v1") -> DomainPack:
    if not all(re.fullmatch(r"[a-zA-Z0-9_-]+", x) for x in (name, version)):
        raise ValueError("Invalid domain pack name or version")
    path = Path(__file__).parent / "packs" / name / f"{version}.yaml"
    # Explicit UTF-8: the pack contains en dashes, and Windows' default codepage mangles them.
    pack = DomainPack.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if (pack.name, pack.version) != (name, version):
        raise ValueError("Domain pack identity does not match its path")
    return pack


def service_def(service_id: str) -> ServiceDef | None:
    return next((s for s in load_pack().services if s.id == service_id), None)


def service_label(service_id: str) -> str:
    """Human label for a service id; falls back to the id itself, prettified."""
    s = service_def(service_id)
    return s.label if s else service_id.replace("_", " ")


def service_terms(service_id: str | None = None) -> list[str]:
    """Synonyms for one service, or for every service in the catalog when service_id is None."""
    if service_id is None:
        return [t for s in load_pack().services for t in s.synonyms]
    s = service_def(service_id)
    return list(s.synonyms) if s else [service_id.replace("_repair", "").replace("_", " ")]
