from datetime import datetime

from src.notifications.scheduler import FridayScheduler


def test_scheduler_runs_once_at_friday_19_ist():
    calls = []
    scheduler = FridayScheduler(lambda: calls.append(True))
    friday_1900 = datetime(2026, 9, 18, 19, 0, tzinfo=scheduler.timezone)

    assert scheduler.run_if_due(friday_1900) is True
    assert scheduler.run_if_due(friday_1900) is False
    assert len(calls) == 1


def test_scheduler_does_not_run_before_target_time():
    calls = []
    scheduler = FridayScheduler(lambda: calls.append(True))
    friday_1859 = datetime(2026, 9, 18, 18, 59, tzinfo=scheduler.timezone)

    assert scheduler.run_if_due(friday_1859) is False
    assert calls == []