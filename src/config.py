import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(name, default=""):
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


@dataclass(frozen=True)
class Settings:
    fpl_api_url: str = _env("FPL_API_URL", "https://fantasy.premierleague.com/api/")
    odds_api_key: str = _env("ODDS_API_KEY")
    gemini_api_key: str = _env("GEMINI_API_KEY")
    gemini_model: str = _env("GEMINI_MODEL", "gemini-3.6-flash")
    odds_api_url: str = _env("ODDS_API_URL", "https://api.the-odds-api.com/v4")
    soccerdata_api_key: str = _env("SOCCERDATA_API_KEY")
    soccerdata_url: str = _env("SOCCERDATA_URL", "https://api.soccerdata.com/v1")
    rss_urls: tuple[str, ...] = tuple(filter(None, (_env("RSS_URLS").split(","))))
    twilio_account_sid: str = _env("TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = _env("TWILIO_AUTH_TOKEN")
    whatsapp_from: str = _env("WHATSAPP_FROM", "whatsapp:+14155238886")
    whatsapp_to: str = _env("WHATSAPP_TO")
    telegram_bot_token: str = _env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = _env("TELEGRAM_CHAT_ID")
    manager_id: int | None = int(_env("FPL_MANAGER_ID")) if _env("FPL_MANAGER_ID") else None
    timezone: str = _env("TIMEZONE", "Asia/Kolkata")
    wildcard_horizon: int = int(_env("WILDCARD_HORIZON", "10"))
    run_artifact_dir: Path = Path(_env("FPL_RUN_ARTIFACT_DIR", ".fplcopilot/runs"))
    news_freshness_hours: float = float(_env("NEWS_FRESHNESS_HOURS", "72"))


settings = Settings()