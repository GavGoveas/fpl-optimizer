from datetime import datetime, timezone
from typing import Any

import requests

from src.config import settings
from src.models.manager_state import TransferLedger
from src.models.rules import FPLRules


class FPLAPIError(RuntimeError):
    pass


class FPLAPI:
    def __init__(self, base_url: str | None = None, session: requests.Session | None = None):
        self.base_url = (base_url or settings.fpl_api_url).rstrip("/") + "/"
        self.session = session or requests.Session()
        self.players: list[dict[str, Any]] = []
        self.teams: list[dict[str, Any]] = []
        self.last_retrieved_at: datetime | None = None

    def _get(self, path: str, **params: Any) -> Any:
        try:
            response = self.session.get(f"{self.base_url}{path}", params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            status = error.response.status_code if error.response is not None else None
            endpoint = path.split("/", 1)[0]
            raise FPLAPIError(f"FPL request failed for endpoint {endpoint}; HTTP status={status}") from None
        except ValueError:
            endpoint = path.split("/", 1)[0]
            raise FPLAPIError(f"FPL response was not valid JSON for endpoint {endpoint}") from None
        self.last_retrieved_at = datetime.now(timezone.utc)
        if not isinstance(payload, (dict, list)):
            raise ValueError(f"Unexpected FPL API payload for {path}")
        return payload

    def get_bootstrap(self) -> dict[str, Any]:
        data = self._get("bootstrap-static/")
        if not isinstance(data, dict) or not isinstance(data.get("events"), list) or not isinstance(data.get("elements"), list) or not isinstance(data.get("teams"), list):
            raise FPLAPIError("FPL bootstrap response is missing required events/elements/teams schema")
        self.players = data.get("elements", [])
        self.teams = data.get("teams", [])
        return data

    def get_players(self):
        return self.get_bootstrap().get("elements", [])

    def get_teams(self):
        if not self.teams:
            self.get_bootstrap()
        return self.teams

    def get_player_data(self, player_id: int):
        if not self.players:
            self.get_bootstrap()
        return next((player for player in self.players if player["id"] == player_id), None)

    def get_team_data(self, team_id: int):
        return next((team for team in self.get_teams() if team["id"] == team_id), None)

    def get_fixtures(self):
        return self._get("fixtures/")

    @staticmethod
    def select_next_gameweek(events, now=None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        future = []
        for event in events:
            if event.get("finished"):
                continue
            deadline_raw = event.get("deadline_time")
            if not deadline_raw:
                continue
            deadline = datetime.fromisoformat(str(deadline_raw).replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                raise ValueError(f"Event {event.get('id')} deadline is not timezone-aware")
            if deadline > now:
                future.append((deadline, event))
        if future:
            return min(future, key=lambda item: item[0])[1]
        # Older/test API payloads may omit deadlines. Prefer explicit next, never previous.
        next_event = next((event for event in events if event.get("is_next") and not event.get("finished")), None)
        if next_event is not None:
            return next_event
        if not any(event.get("deadline_time") for event in events):
            return next((event for event in events if event.get("is_current") and not event.get("finished")), None)
        return None

    def get_next_gameweek(self, now=None):
        event = self.select_next_gameweek(self.get_bootstrap().get("events", []), now)
        return event.get("id") if event else None

    def get_current_gameweek(self):
        """Compatibility name: return the next actionable, not previous, event."""
        return self.get_next_gameweek()

    def get_gameweek_event(self, gameweek=None):
        events = self.get_bootstrap().get("events", [])
        if gameweek is None:
            return self.select_next_gameweek(events)
        return next((event for event in events if event.get("id") == gameweek), None)

    def get_current_gameweek_fixtures(self, gameweek: int | None = None):
        gw = gameweek if gameweek is not None else self.get_current_gameweek()
        if gw is None:
            return []
        fixtures = self._get("fixtures/", event=gw)
        if isinstance(fixtures, list):
            return fixtures
        return fixtures.get("fixtures", [])

    def get_manager_picks(self, manager_id: int, gameweek: int):
        return self._get(f"entry/{manager_id}/event/{gameweek}/picks/")

    def get_manager_history(self, manager_id: int):
        return self._get(f"entry/{manager_id}/history/")

    def get_manager(self, manager_id: int):
        return self._get(f"entry/{manager_id}/")

    def get_manager_free_transfers(self, manager_id: int, gameweek: int | None = None):
        entry = self.get_manager(manager_id)
        history = self.get_manager_history(manager_id)
        bootstrap = self.get_bootstrap()
        rules = FPLRules.from_bootstrap(bootstrap)
        target_gameweek = gameweek
        if target_gameweek is None:
            event = self.select_next_gameweek(bootstrap.get("events", []))
            target_gameweek = event.get("id") if event else None
        if target_gameweek is None:
            raise ValueError("FPL API did not identify an upcoming Gameweek")
        if entry.get("id") is not None and int(entry["id"]) != int(manager_id):
            raise ValueError("FPL manager endpoint returned a different manager ID")
        return self.remaining_free_transfers(history, target_gameweek, rules.max_free_transfers, rules.initial_free_transfers)

    @staticmethod
    def upcoming_free_transfers(history, max_free_transfers=None):
        rules = FPLRules(version="FPL-default")
        max_free_transfers = rules.max_free_transfers if max_free_transfers is None else max_free_transfers
        events = history.get("current", [])
        latest = max((int(item.get("event", 0)) for item in events), default=0)
        if latest <= 0:
            return rules.initial_free_transfers
        return TransferLedger.reconstruct(
            history,
            latest + 1,
            max_free_transfers=max_free_transfers,
            initial_free_transfers=rules.initial_free_transfers,
        ).free_transfers_at_gameweek_start

    @staticmethod
    def remaining_free_transfers(history, gameweek, max_free_transfers=None, initial_free_transfers=None):
        rules = FPLRules(version="FPL-default")
        max_free_transfers = rules.max_free_transfers if max_free_transfers is None else max_free_transfers
        initial_free_transfers = rules.initial_free_transfers if initial_free_transfers is None else initial_free_transfers
        return TransferLedger.reconstruct(history, gameweek, max_free_transfers=max_free_transfers, initial_free_transfers=initial_free_transfers).free_transfers_remaining