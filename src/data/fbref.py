import pandas as pd
import requests


class FBRef:
    BASE_URL = "https://fbref.com/en/comps/9/standard/Premier-League-Stats"

    def __init__(self, url=None, session=None):
        self.url = url or self.BASE_URL
        self.session = session or requests.Session()
        self.player_stats = {}

    def fetch_player_stats(self):
        response = self.session.get(self.url, timeout=20)
        response.raise_for_status()
        self.player_stats = self.parse_stats(response.text)
        return self.player_stats

    def parse_stats(self, html):
        tables = pd.read_html(html)
        standard = next((table for table in tables if "Player" in table.columns), None)
        if standard is None:
            return {}
        standard.columns = [column[-1] if isinstance(column, tuple) else column for column in standard.columns]
        return {
            str(row["Player"]): row.drop(labels=["Player"]).dropna().to_dict()
            for _, row in standard.iterrows()
            if str(row["Player"]) != "nan"
        }

    def get_player_stats(self, player_name):
        if not self.player_stats:
            self.fetch_player_stats()
        return self.player_stats.get(player_name)