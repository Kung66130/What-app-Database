from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path(os.getenv("WA_AGENT_DATA_DIR", str(BASE_DIR / "data")))
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "whatsapp_agent.db"


@dataclass(frozen=True)
class Settings:
    app_name: str = "WhatsApp Agent MVP"
    db_path: Path = Path(os.getenv("WA_AGENT_DB_PATH", str(DEFAULT_DB_PATH)))
    data_dir: Path = DEFAULT_DATA_DIR
    host: str = os.getenv("WA_AGENT_HOST", "127.0.0.1")
    port: int = int(os.getenv("WA_AGENT_PORT", "8080"))
    timezone: str = os.getenv("WA_AGENT_TIMEZONE", "Asia/Bangkok")
    api_key: str = os.getenv("WA_AGENT_API_KEY", "")
    webhook_secret: str = os.getenv("WA_AGENT_WEBHOOK_SECRET", "")
    slack_signing_secret: str = os.getenv("SLACK_SIGNING_SECRET", "")
    slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")
    slack_allowed_channels: str = os.getenv("SLACK_ALLOWED_CHANNELS", "") # Comma separated IDs
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_models: str = os.getenv("GEMINI_MODELS", "gemini-2.5-flash-lite,gemini-2.5-flash")
    evolution_base_url: str = os.getenv("EVOLUTION_BASE_URL", "http://evolution-api:8080")
    evolution_instance: str = os.getenv("EVOLUTION_INSTANCE", "whatsapp-pi-new")
    evolution_api_key: str = os.getenv("EVOLUTION_API_KEY", "")


settings = Settings()
