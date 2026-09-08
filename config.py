"""
Configuration module for Steam Telegram Deals Bot.
Loads environment variables from .env file and provides typed settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID: str = os.getenv("CHANNEL_ID", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID: int | None = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))
COUNTRY_CODE: str = os.getenv("COUNTRY_CODE", "us").strip().lower()
MIN_DISCOUNT_PERCENT: int = int(os.getenv("MIN_DISCOUNT_PERCENT", "10"))
MAX_POSTS_PER_RUN: int = int(os.getenv("MAX_POSTS_PER_RUN", "5"))

# Game Filtering Options
FILTER_ADULT_CONTENT: bool = os.getenv("FILTER_ADULT_CONTENT", "true").lower() in ("true", "1", "yes")
BLOCK_ALL_NUDITY: bool = os.getenv("BLOCK_ALL_NUDITY", "false").lower() in ("true", "1", "yes")
MIN_PRICE_USD: float = float(os.getenv("MIN_PRICE_USD", "0.0"))

DATABASE_PATH = BASE_DIR / "steam_deals.db"


def validate_config() -> tuple[bool, str]:
    """
    Validates essential configuration parameters.
    Returns (is_valid, error_message).
    """
    if not BOT_TOKEN or "YOUR_TELEGRAM_BOT_TOKEN" in BOT_TOKEN:
        return (
            False,
            "BOT_TOKEN sozlanmagan! Iltimos, .env fayliga @BotFather dan olingan haqiqiy bot tokenini kiriting."
        )
    if not CHANNEL_ID or "@your_channel" in CHANNEL_ID:
        return (
            False,
            "CHANNEL_ID sozlanmagan! Iltimos, .env fayliga Telegram kanal username yoki ID sini kiriting."
        )
    return True, "OK"
