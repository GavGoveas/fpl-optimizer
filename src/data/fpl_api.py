from typing import Any

import requests

from src.config import settings


class FPLAPI:
    def __init__(self, base_url: str | None = None, session: requests.Session | None = None):
        self.base_url = (base_url or settings.fpl_api_url).rstrip("/") + "/"
        self.session = session or requests.Session()
        self.players: list[dict[str, Any]] = []
        self.teams: list[dict[str, Any]] = []

    def _get(self, path: str, **params: Any) -> Any:
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def get_bootstrap(self) -> dict[str, Any]:
        data = self._get("bootstrap-static/")
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

    def get_current_gameweek(self):
        events = self.get_bootstrap().get("events", [])
        current = next((event for event in events if event.get("is_current")), None)
        return current["id"] if current else None

    def get_manager_picks(self, manager_id: int, gameweek: int):
        return self._get(f"entry/{manager_id}/event/{gameweek}/picks/")

    def get_manager_history(self, manager_id: int):
        return self._get(f"entry/{manager_id}/history/")

    def get_manager(self, manager_id: int):
        return self._get(f"entry/{manager_id}/")

    @staticmethod
    def upcoming_free_transfers(history):
        available = 1
        for event in sorted(history.get("current", []), key=lambda item: item.get("event", 0)):
            transfers = int(event.get("event_transfers", 0))
            used_free_transfers = min(transfers, available)
            available = min(5, available - used_free_transfers + 1)
        return available

    @staticmethod
    def remaining_free_transfers(history, gameweek):
        available = 1
        for event in sorted(history.get("current", []), key=lambda item: item.get("event", 0)):
            transfers = int(event.get("event_transfers", 0))
            available -= min(transfers, available)
            if event.get("event") == gameweek:
                return available
            available = min(5, available + 1)
        return available