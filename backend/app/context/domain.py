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
    expected: dict = Field(default_factory=dict)


class DomainPack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    version: str
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
    pack = DomainPack.model_validate(yaml.safe_load(path.read_text()))
    if (pack.name, pack.version) != (name, version):
        raise ValueError("Domain pack identity does not match its path")
    return pack
