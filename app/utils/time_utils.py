import datetime
import logging
from zoneinfo import ZoneInfo
from typing import Optional
from app.config import settings

logger = logging.getLogger("app.time_utils")

def get_current_time(tz_name: Optional[str] = None) -> datetime.datetime:
    """
    Returns the current timestamp synchronized with the host device's clock
    and localized to the configured timezone (default: Asia/Kolkata / IST, UTC+05:30).

    Works consistently across Windows and Raspberry Pi (Linux):
    - Uses the host device's system clock (synced via NTP or RTC hardware).
    - If TIMEZONE is 'local', 'system', or 'device', returns host device local time directly.
    - Otherwise, localizes the device time to the requested timezone (e.g., 'Asia/Kolkata').
    - Strips tzinfo to return a naive datetime for clean, uniform storage in SQLite and MSSQL.
    """
    target_tz = tz_name or getattr(settings, "TIMEZONE", "Asia/Kolkata")

    if not target_tz or target_tz.lower() in ("local", "device", "system"):
        return datetime.datetime.now()

    try:
        tz = ZoneInfo(target_tz)
        return datetime.datetime.now(tz).replace(tzinfo=None)
    except Exception as e:
        logger.warning(f"Failed to apply timezone '{target_tz}', falling back to device local time: {e}")
        return datetime.datetime.now()
