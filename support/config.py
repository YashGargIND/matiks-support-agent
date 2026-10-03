from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
# Set BEFORE importing the SDK, which otherwise configures an external exporter.
os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"


def read_config() -> dict:
    from support.settings_service import ConfigService

    return ConfigService().effective()


def db_path() -> Path:
    path = Path(os.getenv("SUPPORT_DB", "data/support.sqlite3"))
    return path if path.is_absolute() else ROOT / path


def require_dry_run() -> None:
    for flag in ("SEND_MODE", "ACTION_MODE", "SLACK_POST_MODE"):
        if os.getenv(flag, "dry_run") != "dry_run":
            raise RuntimeError(f"{flag} must be dry_run. Real execution is unsupported.")


def llm_enabled() -> bool:
    return os.getenv("LLM_ENABLED", "false").lower() == "true"
