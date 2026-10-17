"""Owner: Karthik. Stub from CP0 — replace."""
from __future__ import annotations


def compose_inquiry(task_id: str, provider_id: str) -> str:
    return ("Hi, I need a dishwasher repair visit on Tuesday between 2 and 5 p.m. "
            "What is the total visit charge, including any trip fee, and your cancellation terms?")


def compose_followup(task_id: str, provider_id: str, missing_keys: list[str]) -> str:
    return "Thanks! Could you also confirm: " + ", ".join(missing_keys) + "?"
