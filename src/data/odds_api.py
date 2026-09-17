import os
from datetime import datetime

import requests


class OddsAPI:
    def __init__(self, api_key=None, base_url=None, session=None):
        self.api_key = api_key or os.getenv("ODDS_API_KEY", "")
        self.base_url = (base_url or os.getenv("ODDS_API_URL", "https://api.the-odds-api.com/v4")).rstrip("/")
        self.session = session or requests.Session()
        if not hasattr(self.session, "headers"):
            self.session.headers = {}
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; FPLBot/1.0)"})

    def _request(self, path, params=None, timeout=20):
        if not self.api_key:
            return []
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()

    def get_odds(self, sport="soccer_epl", region="uk", odds_format="decimal"):
        return self._request(
            f"/sports/{sport}/odds",
            params={"apiKey": self.api_key, "regions": region, "oddsFormat": odds_format},
        )

    def get_market_data(self, sport="soccer_epl", region="uk", markets="h2h"):
        data = self._request(
            f"/sports/{sport}/odds",
            params={"apiKey": self.api_key, "regions": region, "markets": markets, "oddsFormat": "decimal"},
        )
        return data if isinstance(data, list) else data.get("data", [])

    def get_event_fixtures(self, sport="soccer_epl", region="uk", bookmakers=None):
        params = {"apiKey": self.api_key, "regions": region}
        if bookmakers:
            params["bookmakers"] = bookmakers
        return self._request(f"/sports/{sport}/odds", params=params)

    def _match_fixture(self, fixture, odds_event):
        if not fixture or not odds_event:
            return False
        home = str(fixture.get("team_h_name") or fixture.get("home_team") or "").lower().strip()
        away = str(fixture.get("team_a_name") or fixture.get("away_team") or "").lower().strip()
        event_home = str(odds_event.get("home_team", "")).lower().strip()
        event_away = str(odds_event.get("away_team", "")).lower().strip()
        if not event_home or not event_away:
            return False
        return (home == event_home and away == event_away) or (home == event_away and away == event_home)

    def map_to_gameweek_fixtures(self, fpl_fixtures, sport="soccer_epl", region="uk", bookmakers="pinnacle"):
        if not fpl_fixtures:
            return []
        events = self.get_event_fixtures(sport=sport, region=region, bookmakers=bookmakers)
        matched = []
        for fixture in fpl_fixtures:
            for event in events:
                if self._match_fixture(fixture, event):
                    matched.append({**event, "fpl_fixture": fixture})
                    break
        return matched

    def get_player_goal_scorer_market(self, sport="soccer_epl", region="uk", fpl_fixtures=None, fixture_ids=None):
        if not self.api_key:
            return []
        fixtures = []
        if fpl_fixtures:
            fixtures = self.map_to_gameweek_fixtures(fpl_fixtures, sport=sport, region=region)
        elif fixture_ids:
            fixtures = [{"id": fixture_id} for fixture_id in fixture_ids]
        else:
            fixtures = self.get_event_fixtures(sport=sport, region=region)
        players = []
        seen = set()
        for match in fixtures:
            event_id = match.get("id")
            if not event_id:
                continue
            market_data = self._request(
                f"/sports/{sport}/events/{event_id}/odds",
                params={"apiKey": self.api_key, "regions": region, "markets": "player_goal_scorer_anytime"},
            )
            for bookmaker in market_data.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "player_goal_scorer_anytime":
                        continue
                    raw_outcomes = [outcome for outcome in market.get("outcomes", []) if float(outcome.get("price") or 0) > 1]
                    implied = [1.0 / float(outcome["price"]) for outcome in raw_outcomes]
                    overround = sum(implied)
                    for outcome in market.get("outcomes", []):
                        name = (outcome.get("description") or outcome.get("name") or "").strip()
                        if not name or name.lower() in {"yes", "no"}:
                            continue
                        price = float(outcome.get("price") or 0)
                        if price <= 1:
                            continue
                        probability = (1.0 / price) / overround if overround else 0.0
                        key = (name, event_id)
                        if key in seen:
                            continue
                        seen.add(key)
                        players.append({
                            "player": name,
                            "fixture_id": event_id,
                            "game": match.get("home_team") + " vs " + match.get("away_team"),
                            "price": price,
                            "probability": max(0.0, min(1.0, probability)),
                        })
        return sorted(players, key=lambda item: item["probability"], reverse=True)

    def get_team_odds(self, team_name):
        return [match for match in self.get_market_data() if team_name in (match.get("home_team"), match.get("away_team"))]