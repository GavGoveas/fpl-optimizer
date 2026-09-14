class ProjectionEngine:
    def project(self, players, fixtures=None, gameweek=None, news=None, fbref_stats=None, odds=None):
        fixture_map = self._fixture_map(fixtures or [], gameweek)
        news_text = " ".join(self._news_text(item) for item in (news or []))
        projections = []
        for player in players:
            name = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
            base = float(player.get("ep_next") or player.get("form") or 0)
            difficulty = fixture_map.get(player.get("team"), 3.0)
            multiplier = max(0.65, min(1.25, 1.15 - (difficulty - 1) * 0.125))
            availability = self._availability(player, name, news_text)
            enriched = dict(player)
            enriched.update({
                "name": name,
                "fixture_difficulty": difficulty,
                "availability": availability,
                "expected_points": round(base * multiplier * availability, 2),
            })
            projections.append(enriched)
        return projections

    @staticmethod
    def _fixture_map(fixtures, gameweek):
        values = {}
        for fixture in fixtures:
            if gameweek is not None and fixture.get("event") not in (gameweek + 1, gameweek + 2):
                continue
            for team_key, difficulty_key in (("team_h", "team_h_difficulty"), ("team_a", "team_a_difficulty")):
                team = fixture.get(team_key)
                difficulty = fixture.get(difficulty_key)
                if team is not None and difficulty is not None:
                    values.setdefault(team, []).append(float(difficulty))
        return {team: sum(scores) / len(scores) for team, scores in values.items()}

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
    def _news_text(item):
        return f"{item.get('title', '')} {item.get('summary', '')}".lower()


Projections = ProjectionEngine