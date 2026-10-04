\
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _b(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default

@dataclass(frozen=True)
class Settings:
    ao_username: str = os.getenv("AO_USERNAME", "").strip()
    ao_password: str = os.getenv("AO_PASSWORD", "").strip()
    ao_password_is_md5: bool = _b("AO_PASSWORD_IS_MD5", False)

    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    scan_seconds: float = max(5.05, _f("SCAN_SECONDS", 5.2))
    min_alert_score: int = _i("MIN_ALERT_SCORE", 75)
    extreme_alert_score: int = _i("EXTREME_ALERT_SCORE", 90)
    alert_cooldown_seconds: int = _i("ALERT_COOLDOWN_SECONDS", 120)
    event_cooldown_seconds: int = _i("EVENT_COOLDOWN_SECONDS", 75)
    min_confirming_bookie_count: int = _i("MIN_CONFIRMING_BOOKIE_COUNT", 2)
    sharp_bookie_ids: frozenset[str] = frozenset(
        x.strip().upper()
        for x in os.getenv("SHARP_BOOKIE_IDS", "PIN,SBO,SIN,IBC,ISN").split(",")
        if x.strip()
    )

    start_scanner: bool = _b("START_SCANNER", True)
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

settings = Settings()
