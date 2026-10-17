"""Owner: Karthik. Stub from CP0 — replace."""
from __future__ import annotations

from app.core.schemas import VerificationResult


async def summarize(task_id: str, verification: VerificationResult) -> str:
    return (f"Verification: {verification.verdict.value}. "
            "Parts and labor are unknown until diagnosis.")
