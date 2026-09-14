import os

import requests

class SoccerData:
    def __init__(self, api_key=None, base_url=None, session=None):
        self.api_key = api_key or os.getenv("SOCCERDATA_API_KEY", "")
        self.base_url = (base_url or os.getenv("SOCCERDATA_URL", "https://api.soccerdata.com/v1")).rstrip("/")
        self.session = session or requests.Session()

    def _get(self, path):
        response = self.session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def get_league_data(self, league_id):
        return self._get(f"leagues/{league_id}")

    def get_team_data(self, team_id):
        return self._get(f"teams/{team_id}")

    def get_player_data(self, player_id):
        return self._get(f"players/{player_id}")

    def get_match_data(self, match_id):
        return self._get(f"matches/{match_id}")

    def get_injury_updates(self):
        return self._get("injuries")

    def get_recent_results(self, team_id):
        return self._get(f"teams/{team_id}/results")

    fetch_league_data = get_league_data
    fetch_team_data = get_team_data
    fetch_player_data = get_player_data
    fetch_match_data = get_match_data
    fetch_injury_updates = get_injury_updates