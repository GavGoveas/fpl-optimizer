class ProjectionEngine:
    def project(self, players, fixtures=None, gameweek=None, news=None, fbref_stats=None, odds=None, wildcard_horizon=3):
        fixture_map = self._fixture_map(fixtures or [], gameweek)
        horizon_maps = self._fixture_maps(fixtures or [], gameweek, wildcard_horizon)
        news_text = " ".join(self._news_text(item) for item in (news or []))
        projections = []
        for player in players:
            name = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
            base = float(player.get("ep_next") or player.get("form") or 0)
            difficulty = fixture_map.get(player.get("team"), 3.0)
            multiplier = max(0.65, min(1.25, 1.15 - (difficulty - 1) * 0.125))
            availability = self._availability(player, name, news_text)
            minutes_probability = self._minutes_probability(player)
            base *= self._fbref_multiplier(name, fbref_stats or {})
            base *= self._odds_multiplier(player, odds or [])
            horizon_points = 0.0
            horizon_fixtures = horizon_maps.get(player.get("team"), [])
            if not horizon_fixtures:
                horizon_fixtures = [difficulty] * wildcard_horizon
            for week_index, horizon_difficulty in enumerate(horizon_fixtures[:wildcard_horizon]):
                horizon_multiplier = max(0.65, min(1.25, 1.15 - (horizon_difficulty - 1) * 0.125))
                horizon_confidence = max(0.55, 1.0 - week_index * 0.05)
                horizon_points += base * horizon_multiplier * availability * minutes_probability * horizon_confidence
            enriched = dict(player)
            enriched.update({
                "name": name,
                "fixture_difficulty": difficulty,
                "availability": availability,
                "expected_minutes": round(90 * minutes_probability, 1),
                "expected_points": round(base * multiplier * availability * minutes_probability, 2),
                "wildcard_expected_points": round(horizon_points, 2),
                "wildcard_confidence": round(max(0.55, 1.0 - max(0, len(horizon_fixtures) - 1) * 0.025), 2),
            })
            projections.append(enriched)
        return projections

    @staticmethod
    def _fixture_map(fixtures, gameweek):
        values = {}
        for fixture in fixtures:
            if gameweek is not None and fixture.get("event") != gameweek + 1:
                continue
            for team_key, difficulty_key in (("team_h", "team_h_difficulty"), ("team_a", "team_a_difficulty")):
                team = fixture.get(team_key)
                difficulty = fixture.get(difficulty_key)
                if team is not None and difficulty is not None:
                    values.setdefault(team, []).append(float(difficulty))
        return {team: sum(scores) / len(scores) for team, scores in values.items()}

    @staticmethod
    def _fixture_maps(fixtures, gameweek, horizon):
        values = {}
        first_event = (gameweek or 0) + 1
        for fixture in fixtures:
            event = fixture.get("event")
            if event not in range(first_event, first_event + horizon):
                continue
            for team_key, difficulty_key in (("team_h", "team_h_difficulty"), ("team_a", "team_a_difficulty")):
                team = fixture.get(team_key)
                difficulty = fixture.get(difficulty_key)
                if team is not None and difficulty is not None:
                    values.setdefault(team, {}).setdefault(event, []).append(float(difficulty))
        return {team: [sum(values_by_event[event]) / len(values_by_event[event]) for event in sorted(values_by_event)] for team, values_by_event in values.items()}

    @staticmethod
    def _availability(player, name, news_text):
        if player.get("status", "a") in {"i", "s", "u"}:
            return 0.0
        chance = player.get("chance_of_playing_next_round")
        if chance is not None and chance <= 25:
            return 0.0
        if name and name.lower() in news_text and chance is None:
            return 0.75
        return 1.0

    @staticmethod
    def _minutes_probability(player):
        chance = player.get("chance_of_playing_next_round")
        if chance is not None:
            return max(0.0, min(1.0, float(chance) / 100))
        minutes = float(player.get("minutes", 0) or 0)
        starts = float(player.get("starts", 0) or 0)
        if minutes <= 0:
            return 0.35
        historical_start_rate = starts / max(1.0, minutes / 90)
        return max(0.35, min(1.0, historical_start_rate))

    @staticmethod
    def _news_text(item):
        return f"{item.get('title', '')} {item.get('summary', '')} {item.get('gemini_analysis', '')}".lower()

    @staticmethod
    def _fbref_multiplier(name, stats):
        values = stats.get(name, {})
        attacking = sum(float(values.get(key, 0) or 0) for key in ("xG", "xAG", "Gls", "Ast"))
        return 1.0 + min(0.15, attacking / 100)

    @staticmethod
    def _odds_multiplier(player, odds):
        team_name = player.get("team_name", "").lower()
        for match in odds:
            if team_name not in {str(match.get("home_team", "")).lower(), str(match.get("away_team", "")).lower()}:
                continue
            home = str(match.get("home_team", "")).lower() == team_name
            probability = 0.5
            for bookmaker in match.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    outcome = next((item for item in market.get("outcomes", []) if item.get("name") == match.get("home_team" if home else "away_team")), None)
                    if outcome and outcome.get("price"):
                        probability = 1 / float(outcome["price"])
                        break
            return max(0.85, min(1.15, 0.85 + probability * 0.3))
        return 1.0


Projections = ProjectionEngine