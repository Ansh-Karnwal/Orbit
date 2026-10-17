"""Owner: Ansh. Photon inbound arrives by polling (see photon.py), so no webhook route is mounted.

Photon Beta webhook signature verification is undocumented as of 2026-10-17; add a router here
only once it is, and verify signatures before trusting any payload.
"""
from __future__ import annotations

from fastapi import APIRouter

router: APIRouter | None = None
