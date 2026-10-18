"""Owner: Victor. Settings read from env / .env (see .env.example)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    orbit_mode: Literal["fixture", "live"] = "fixture"
    orbit_allow_reset: bool = True
    # demo: no sign-in needed (anonymous = demo_user); required: 401 until signed in.
    orbit_auth_mode: Literal["demo", "required"] = "demo"
    # Let the task owner approve/decline by texting "YES <hash8>" / "NO <hash8>". Off by default.
    orbit_text_approvals: bool = False
    # A text from LIVE_USER_HANDLE with no active task starts one (seeded constraints, live providers).
    orbit_text_intake: bool = False
    # After the user approves, text the provider the approved terms and book only once they reply YES.
    orbit_provider_confirm: bool = False
    database_url: str = "sqlite:///./orbit.db"
    artifact_dir: str = "./artifacts"

    llm_mode: Literal["fixture", "live"] = "fixture"
    llm_provider: str = "gemini"
    llm_model: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    messaging_mode: Literal["fixture", "photon"] = "fixture"
    photon_api_key: str = ""
    photon_bridge_url: str = "http://localhost:8200"
    live_provider_a_handle: str = ""
    live_provider_b_handle: str = ""
    live_user_handle: str = ""             # the demo user's own number, for Orbit's reports

    browser_mode: Literal["fixture", "browser_use"] = "fixture"
    browser_use_api_key: str = ""
    portal_base_url: str = "http://localhost:8100"

    fixture_auto_followups: bool = False
    sentry_dsn: str = ""
    sentry_environment: str = "development"
    sentry_release: str = ""
    sentry_traces_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
