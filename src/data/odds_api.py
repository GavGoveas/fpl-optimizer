import os

import requests


class OddsAPI:
    def __init__(self, api_key=None, base_url=None, session=None):
        self.api_key = api_key or os.getenv("ODDS_API_KEY", "")
        self.base_url = (base_url or os.getenv("ODDS_API_URL", "https://api.the-odds-api.com/v4")).rstrip("/")
        self.session = session or requests.Session()

    def get_odds(self, sport="soccer_epl", region="uk", odds_format="decimal"):
        response = self.session.get(
            f"{self.base_url}/sports/{sport}/odds",
            params={"apiKey": self.api_key, "regions": region, "oddsFormat": odds_format},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def get_market_data(self, sport="soccer_epl"):
        data = self.get_odds(sport=sport)
        return data.get("data", data) if isinstance(data, dict) else data

    def get_team_odds(self, team_name):
        return [match for match in self.get_market_data() if team_name in (match.get("home_team"), match.get("away_team"))]