"""Owner: Ansh. Integration-only env vars that core Settings doesn't carry (it ignores extras).

Reads the same .env files as app.core.config. Proposed additions to .env.example (via Victor):
PHOTON_PROJECT_ID, PHOTON_AGENT_HANDLE, PHOTON_POLL_S, BROWSER_USE_HEADLESS, BROWSER_USE_LLM,
BROWSER_USE_MODEL, BROWSER_USE_MAX_STEPS, BROWSER_USE_TIMEOUT_S.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class IntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Photon Beta (photonhq-api). Key itself is PHOTON_API_KEY in core Settings.
    photon_project_id: str = ""
    photon_agent_handle: str = ""          # the shared line assigned to the project (display only)
    photon_poll_s: float = 2.0

    # Browser Use open-source library.
    browser_use_headless: bool = False     # visible Chromium is nicer for the live demo
    browser_use_llm: Literal["auto", "browser_use", "anthropic"] = "auto"
    browser_use_model: str = ""            # model id for the chosen LLM; empty = library default
    browser_use_max_steps: int = 25
    browser_use_timeout_s: float = 120.0


@lru_cache
def get_integration_settings() -> IntegrationSettings:
    return IntegrationSettings()
