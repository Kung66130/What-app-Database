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
    slack_signing_secret: str = os.getenv("SLACK_SIGNING_SECRET", "")
    slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")
    slack_allowed_channels: str = os.getenv("SLACK_ALLOWED_CHANNELS", "") # Comma separated IDs


settings = Settings()
