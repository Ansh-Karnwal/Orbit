"""Extraction output: data only, with no actions, constraints or approval fields."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

USD = Annotated[str, Field(pattern=r"^\d+(?:\.\d{1,2})?$")]


class QuoteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ExtraFee(QuoteModel):
    name: str
    usd: USD


class QuoteSlot(QuoteModel):
    day_text: str
    start_local: str
    end_local: str


class ProviderQuoteExtraction(QuoteModel):
    service_supported: bool | None = None
    base_charge_usd: USD | None = None
    extra_fees: list[ExtraFee] | None = None
    total_visit_charge_usd: USD | None = None
    fee_scope: Literal["diagnostic_visit_including_travel", "diagnostic_visit_excluding_travel", "flat_repair", "unknown"] | None = None
    slots: list[QuoteSlot] | None = None
    cancellation_terms: str | None = None
    repair_cost_after_diagnosis: bool | None = None
    is_correction: bool = False
    confidence_notes: list[str] = Field(default_factory=list)
