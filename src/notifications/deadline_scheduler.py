from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


STAGE_OFFSETS_MINUTES = (1440, 720, 360, 180, 120, 90, 75, 60, 30, 0)
POLL_INTERVAL_MINUTES = 15
DEFAULT_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"


@dataclass(frozen=True)
class DueStage:
    gameweek: int
    deadline: datetime
    stage_offset_minutes: int
    deadline_key: str
    notify: bool


class DeadlineStageStore:
    def __init__(self, path: str | Path, claim_lease: timedelta = timedelta(minutes=30)):
        self.path = Path(path)
        self.claim_lease = claim_lease
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS deadline_stages ("
                "deadline_key TEXT NOT NULL, offset_minutes INTEGER NOT NULL, "
                "status TEXT NOT NULL, claimed_at_utc TEXT, notified INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY (deadline_key, offset_minutes))"
            )

    def claim_due_stage(self, event: dict[str, Any], now: datetime | None = None) -> DueStage | None:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        deadline = self._parse_utc(event.get("deadline_time"))
        if deadline is None or event.get("finished"):
            return None
        now_utc = now.astimezone(timezone.utc)
        minutes_until = (deadline - now_utc).total_seconds() / 60
        if minutes_until <= 0:
            return None
        due_offsets = [offset for offset in STAGE_OFFSETS_MINUTES if 0 < offset and minutes_until <= offset]
        if 0 < minutes_until <= POLL_INTERVAL_MINUTES:
            due_offsets.append(0)
        if not due_offsets:
            return None
        selected_offset = min(due_offsets)
        event_id = event.get("id")
        if event_id is None:
            return None
        deadline_key = f"{event_id}:{deadline.isoformat()}"
        now_text = now_utc.isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT offset_minutes, status, claimed_at_utc, notified FROM deadline_stages WHERE deadline_key = ?",
                (deadline_key,),
            ).fetchall()
            existing = {int(row[0]): row for row in rows}
            already_notified = any(bool(row[3]) for row in rows)
            selected = existing.get(selected_offset)
            if selected and selected[1] == "completed":
                return None
            if selected and selected[1] == "claimed" and selected[2]:
                claimed_at = self._parse_utc(selected[2])
                if claimed_at and now_utc - claimed_at < self.claim_lease:
                    return None
            connection.execute(
                "INSERT INTO deadline_stages (deadline_key, offset_minutes, status, claimed_at_utc, notified) "
                "VALUES (?, ?, 'claimed', ?, COALESCE((SELECT notified FROM deadline_stages WHERE deadline_key = ? AND offset_minutes = ?), 0)) "
                "ON CONFLICT(deadline_key, offset_minutes) DO UPDATE SET status = 'claimed', claimed_at_utc = excluded.claimed_at_utc",
                (deadline_key, selected_offset, now_text, deadline_key, selected_offset),
            )
            for offset in due_offsets:
                if offset <= selected_offset:
                    continue
                prior = existing.get(offset)
                if prior is None:
                    connection.execute(
                        "INSERT OR IGNORE INTO deadline_stages (deadline_key, offset_minutes, status, claimed_at_utc) VALUES (?, ?, 'skipped', ?)",
                        (deadline_key, offset, now_text),
                    )
            should_notify = selected_offset <= 90 and not already_notified
            return DueStage(int(event_id), deadline, selected_offset, deadline_key, should_notify)

    def complete(self, stage: DueStage, notified: bool = False) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE deadline_stages SET status = 'completed', claimed_at_utc = ?, notified = MAX(notified, ?) "
                "WHERE deadline_key = ? AND offset_minutes = ?",
                (datetime.now(timezone.utc).isoformat(), int(notified), stage.deadline_key, stage.stage_offset_minutes),
            )

    def release(self, stage: DueStage) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE deadline_stages SET status = 'pending', claimed_at_utc = NULL "
                "WHERE deadline_key = ? AND offset_minutes = ? AND status = 'claimed'",
                (stage.deadline_key, stage.stage_offset_minutes),
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _parse_utc(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)


def fetch_bootstrap(url=DEFAULT_BOOTSTRAP_URL):
    request = urllib.request.Request(url, headers={"User-Agent": "FPL-Copilot/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("FPL bootstrap payload has no events array")
    return payload


def select_next_event(events, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    upcoming = []
    for event in events:
        if event.get("finished") or not event.get("deadline_time"):
            continue
        deadline = DeadlineStageStore._parse_utc(event["deadline_time"])
        if deadline and deadline > now.astimezone(timezone.utc):
            upcoming.append((deadline, event))
    return min(upcoming, key=lambda pair: pair[0])[1] if upcoming else None


def probe():
    configured_url = os.getenv("FPL_API_URL", "").strip()
    bootstrap_url = (configured_url or DEFAULT_BOOTSTRAP_URL).rstrip("/") + "/bootstrap-static/"
    bootstrap = fetch_bootstrap(bootstrap_url)
    now = datetime.now(timezone.utc)
    event = select_next_event(bootstrap["events"], now)
    store_path = Path(os.getenv("FPL_SCHEDULE_STATE_PATH", ".fplcopilot/scheduler.sqlite"))
    stage = DeadlineStageStore(store_path).claim_due_stage(event, now) if event else None
    output = {
        "due": stage is not None,
        "gameweek": stage.gameweek if stage else "",
        "deadline": stage.deadline.isoformat().replace("+00:00", "Z") if stage else "",
        "stage_offset_minutes": stage.stage_offset_minutes if stage else "",
        "deadline_key": stage.deadline_key if stage else "",
        "notify": str(stage.notify).lower() if stage else "false",
    }
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as stream:
            for key, value in output.items():
                stream.write(f"{key}={value}\n")
    print(json.dumps({"due": output["due"], "stage_offset_minutes": output["stage_offset_minutes"]}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(probe())
    except Exception as error:
        print(json.dumps({"probe_error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        raise SystemExit(1)
