"""Voice-specific settings, read from the repo-root .env (all optional in dev)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[5]

# Prebuilt Gemini voices an agent may use. Checked again in M3 against the provider docs.
VOICES = ("Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr")


class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore", env_prefix="VOICE_")

    # Vertex AI. The project and location default to the GCP project the app runs in.
    gcp_project: str = ""
    gcp_location: str = "us-central1"
    model: str = "gemini-live-2.5-flash-native-audio"
    max_call_seconds: int = 600
    max_concurrent_calls: int = 50  # per API instance; extra calls are refused politely

    # Custom tools. The key encrypts tool auth headers at rest; required outside dev and test.
    secrets_key: str = ""
    # Dev and tests only: lets tools call localhost and private addresses. Never enable in production.
    tool_allow_private_hosts: bool = False


@lru_cache
def get_voice_settings() -> VoiceSettings:
    return VoiceSettings()
