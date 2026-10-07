from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import settings


class FridayScheduler:
    """Run a callback once when Friday 21:00 is reached in the configured zone."""

    def __init__(self, job, timezone=settings.timezone, day=settings.notification_day, time=settings.notification_time):
        self.job = job
        self.timezone = ZoneInfo(timezone)
        self.day = day.lower()
        self.hour, self.minute = (int(value) for value in time.split(":", 1))
        self.last_run_date = None

    def run_if_due(self, now=None):
        local_now = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        is_target_day = local_now.strftime("%A").lower() == self.day
        is_target_time = (local_now.hour, local_now.minute) >= (self.hour, self.minute)
        if not is_target_day or not is_target_time or self.last_run_date == local_now.date():
            return False

        self.job()
        self.last_run_date = local_now.date()
        return True