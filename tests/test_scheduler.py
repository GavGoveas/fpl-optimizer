from datetime import datetime

from src.notifications.scheduler import FridayScheduler


def test_scheduler_runs_once_at_friday_21_ist():
    calls = []
    scheduler = FridayScheduler(lambda: calls.append(True), time="21:00")
    friday_2100 = datetime(2026, 9, 18, 21, 0, tzinfo=scheduler.timezone)

    assert scheduler.run_if_due(friday_2100) is True
    assert scheduler.run_if_due(friday_2100) is False
    assert len(calls) == 1


def test_scheduler_does_not_run_before_target_time():
    calls = []
    scheduler = FridayScheduler(lambda: calls.append(True), time="21:00")
    friday_2059 = datetime(2026, 9, 18, 20, 59, tzinfo=scheduler.timezone)

    assert scheduler.run_if_due(friday_2059) is False
    assert calls == []