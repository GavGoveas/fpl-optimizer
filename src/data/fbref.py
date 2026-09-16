import time

import pandas as pd
import requests


class FBRef:
    BASE_URL = "https://fbref.com/en/comps/9/standard/Premier-League-Stats"

    def __init__(self, url=None, session=None):
        self.url = url or self.BASE_URL
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        })
        self.player_stats = {}
        self.team_stats = {}

    def fetch_player_stats(self):
        for retry in range(3):
            try:
                response = self.session.get(self.url, timeout=25)
                if response.status_code == 403:
                    raise requests.HTTPError("FBRef access forbidden")
                response.raise_for_status()
                self.player_stats = self.parse_stats(response.text)
                return self.player_stats
            except Exception:
                time.sleep(1.5 * (retry + 1))
        self.player_stats = {}
        return self.player_stats

    def fetch_team_stats(self):
        return self.team_stats

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