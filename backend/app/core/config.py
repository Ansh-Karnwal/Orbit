"""Owner: Victor. Settings read from env / .env (see .env.example)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    orbit_mode: Literal["fixture", "live"] = "fixture"
    orbit_allow_reset: bool = True
    # demo: no sign-in needed (anonymous = demo_user); required: 401 until signed in.
    orbit_auth_mode: Literal["demo", "required"] = "demo"
    # Let the task owner approve/decline by texting "YES <hash8>" / "NO <hash8>". Off by default.
    orbit_text_approvals: bool = False
    database_url: str = "sqlite:///./orbit.db"
    artifact_dir: str = "./artifacts"

    llm_mode: Literal["fixture", "live"] = "fixture"
    llm_provider: str = "anthropic"
    llm_model: str = ""
    anthropic_api_key: str = ""

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
