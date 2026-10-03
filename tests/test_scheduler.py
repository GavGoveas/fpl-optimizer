from datetime import datetime, timedelta, timezone

from src.notifications.deadline_scheduler import DeadlineStageStore


def test_deadline_stages_follow_dynamic_utc_deadline_and_notify_once(tmp_path):
    deadline = datetime(2026, 11, 14, 13, 37, tzinfo=timezone.utc)
    event = {"id": 17, "deadline_time": deadline.isoformat(), "finished": False}
    store = DeadlineStageStore(tmp_path / "schedule.sqlite")

    first = store.claim_due_stage(event, deadline - timedelta(hours=24))
    assert first is not None and first.stage_offset_minutes == 1440 and not first.notify
    store.complete(first)

    second = store.claim_due_stage(event, deadline - timedelta(hours=12))
    assert second is not None and second.stage_offset_minutes == 720
    store.complete(second)

    final = store.claim_due_stage(event, deadline - timedelta(minutes=90))
    assert final is not None and final.stage_offset_minutes == 90 and final.notify
    store.complete(final, notified=True)

    later = store.claim_due_stage(event, deadline - timedelta(minutes=75))
    assert later is not None and later.stage_offset_minutes == 75 and not later.notify


def test_deadline_stage_state_survives_restart_and_deduplicates(tmp_path):
    deadline = datetime(2026, 11, 14, 13, 37, tzinfo=timezone.utc)
    event = {"id": 17, "deadline_time": deadline.isoformat(), "finished": False}
    path = tmp_path / "schedule.sqlite"

    claim = DeadlineStageStore(path).claim_due_stage(event, deadline - timedelta(hours=24))
    duplicate = DeadlineStageStore(path).claim_due_stage(event, deadline - timedelta(hours=24) + timedelta(minutes=1))

    assert claim is not None
    assert duplicate is None


def test_deadline_change_creates_new_schedule_identity(tmp_path):
    store = DeadlineStageStore(tmp_path / "schedule.sqlite")
    original = datetime(2026, 11, 14, 13, 37, tzinfo=timezone.utc)
    rescheduled = original + timedelta(hours=3)

    original_stage = store.claim_due_stage({"id": 17, "deadline_time": original.isoformat()}, original - timedelta(hours=24))
    changed_stage = store.claim_due_stage({"id": 17, "deadline_time": rescheduled.isoformat()}, rescheduled - timedelta(hours=24))

    assert original_stage is not None
    assert changed_stage is not None
    assert original_stage.deadline_key != changed_stage.deadline_key


def test_t0_stage_runs_before_lock_and_never_after_deadline(tmp_path):
    deadline = datetime(2026, 11, 14, 13, 37, tzinfo=timezone.utc)
    event = {"id": 17, "deadline_time": deadline.isoformat(), "finished": False}
    store = DeadlineStageStore(tmp_path / "schedule.sqlite")

    final_refresh = store.claim_due_stage(event, deadline - timedelta(minutes=5))
    after_lock = store.claim_due_stage(event, deadline + timedelta(minutes=1))

    assert final_refresh is not None
    assert final_refresh.stage_offset_minutes == 0
    assert after_lock is None