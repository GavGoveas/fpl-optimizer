import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    fpl_api_url: str = os.getenv("FPL_API_URL", "https://fantasy.premierleague.com/api/")
    odds_api_key: str = os.getenv("ODDS_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    odds_api_url: str = os.getenv("ODDS_API_URL", "https://api.the-odds-api.com/v4")
    soccerdata_api_key: str = os.getenv("SOCCERDATA_API_KEY", "")
    soccerdata_url: str = os.getenv("SOCCERDATA_URL", "https://api.soccerdata.com/v1")
    rss_urls: tuple[str, ...] = tuple(filter(None, os.getenv("RSS_URLS", "").split(",")))
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    whatsapp_from: str = os.getenv("WHATSAPP_FROM", "whatsapp:+14155238886")
    whatsapp_to: str = os.getenv("WHATSAPP_TO", "")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    manager_id: int | None = int(os.environ["FPL_MANAGER_ID"]) if os.getenv("FPL_MANAGER_ID") else None
    free_transfers_override: int | None = int(os.environ["FPL_FREE_TRANSFERS"]) if os.getenv("FPL_FREE_TRANSFERS") else None
    notification_day: str = os.getenv("NOTIFICATION_DAY", "Friday")
    notification_time: str = os.getenv("NOTIFICATION_TIME", "19:00")
    timezone: str = os.getenv("TIMEZONE", "Asia/Kolkata")
    chip_minimum_gain: float = float(os.getenv("CHIP_MINIMUM_GAIN", "4"))


settings = Settings()