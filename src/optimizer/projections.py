from src.optimizer.simulation import PlayerPointSimulator
from datetime import datetime, timedelta, timezone


class ProjectionEngine:
    def __init__(self, simulator=None):
        self.simulator = simulator or PlayerPointSimulator()

    def project(self, players, fixtures=None, gameweek=None, news=None, fbref_stats=None, odds=None, wildcard_horizon=3, news_freshness_hours=72, prediction_time=None):
        fixture_map = self._fixture_map(fixtures or [], gameweek)
        now = prediction_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("prediction_time must be timezone-aware")
        freshness_limit = timedelta(hours=max(0.0, float(news_freshness_hours)))
        news_items = [item for item in (news or []) if self._news_is_fresh(item, now, freshness_limit)]
        projections = []
        for player in players:
            name = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
            base = float(player.get("ep_next") or 0)
            difficulty = fixture_map.get(player.get("team"))
            fixture_count = sum(
                1 for fixture in fixtures or []
                if fixture.get("event") == gameweek
                and player.get("team") in (fixture.get("team_h"), fixture.get("team_a"))
            )
            availability = self._availability(player, name, news_items)
            minutes_probability = self._minutes_probability(player, name, news_items)
            attacking_signal, set_piece_signal = self._captain_evidence(name, fbref_stats or {}, player)
            goal_probability = self._player_goal_probability(player, odds or [])
            source_stats = (fbref_stats or {}).get(name, {})
            ninety_minutes = float(source_stats.get("90s", 0) or 0)
            expected_goals = float(source_stats.get("xG", 0) or 0) / ninety_minutes * minutes_probability if ninety_minutes > 0 else None
            expected_assists = float(source_stats.get("xAG", 0) or 0) / ninety_minutes * minutes_probability if ninety_minutes > 0 else None
            horizon_points = 0.0
            expected_points_by_event = player.get("expected_points_by_event", {})
            first_event = gameweek if gameweek is not None else 1
            horizon_events = range(first_event, first_event + max(0, wildcard_horizon))
            for event in horizon_events:
                event_points = expected_points_by_event.get(str(event), expected_points_by_event.get(event))
                if event_points is not None:
                    horizon_points += max(0.0, float(event_points)) * availability
            enriched = dict(player)
            enriched.update({
                "name": name,
                "fixture_difficulty": difficulty,
                "availability": availability,
                "expected_minutes": round(90 * minutes_probability, 1),
                "expected_points": round(base * (availability if availability is not None else 1.0), 2) if fixture_count else 0.0,
                "availability_verified": availability is not None,
                "wildcard_expected_points": round(horizon_points, 2),
                "wildcard_confidence": round(sum(event in expected_points_by_event or str(event) in expected_points_by_event for event in horizon_events) / max(1, wildcard_horizon), 2),
                "wildcard_projection_available": bool(expected_points_by_event),
                "fixture_count": fixture_count,
                "attacking_involvement": round(attacking_signal, 4),
                "set_piece_involvement": round(set_piece_signal, 4),
                "anytime_goal_probability": round(goal_probability, 4),
            })
            enriched["minutes_probability"] = round(minutes_probability, 3)
            clean_sheet_probability = self._fixture_clean_sheet_probability(fixtures or [], player.get("team"), gameweek)
            enriched["clean_sheet_probability"] = clean_sheet_probability
            enriched["expected_goals"] = expected_goals
            enriched["expected_assists"] = expected_assists
            enriched["fbref_metrics"] = source_stats
            enriched["distribution"] = self.simulator.simulate(enriched)
            projections.append(enriched)
        return projections

    @staticmethod
    def _fixture_map(fixtures, gameweek):
        values = {}
        for fixture in fixtures:
            if gameweek is not None and fixture.get("event") != gameweek:
                continue
            for team_key, difficulty_key in (("team_h", "team_h_difficulty"), ("team_a", "team_a_difficulty")):
                team = fixture.get(team_key)
                difficulty = fixture.get(difficulty_key)
                if team is not None and difficulty is not None:
                    values.setdefault(team, []).append(float(difficulty))
        return {team: sum(scores) / len(scores) for team, scores in values.items()}

    @staticmethod
    def _availability(player, name, news_items):
        if player.get("status", "a") in {"i", "s", "u"}:
            return 0.0
        chance = player.get("chance_of_playing_next_round")
        if chance is not None and chance <= 25:
            return 0.0
        normalized_name = ProjectionEngine._normalize_name(name)
        for item in news_items:
            analysis = item.get("gemini_analysis")
            if not isinstance(analysis, dict):
                continue
            names = [ProjectionEngine._normalize_name(value) for value in analysis.get("player_names", [])]
            if normalized_name not in names:
                continue
            status = str(analysis.get("status", "unknown")).lower()
            if status in {"injured", "suspended", "ruled_out"}:
                return 0.0
            if status == "doubtful":
                probability = analysis.get("availability_probability")
                if probability is not None:
                    return max(0.0, min(1.0, float(probability)))
                continue
            if status in {"available", "expected_to_start"}:
                return 1.0
        if chance is not None:
            return max(0.0, min(1.0, float(chance) / 100))
        if player.get("status") == "d":
            return None
        return 1.0

    @staticmethod
    def _minutes_probability(player, name, news_items):
        chance = player.get("chance_of_playing_next_round")
        if chance is not None:
            return max(0.0, min(1.0, float(chance) / 100))
        normalized_name = ProjectionEngine._normalize_name(name)
        for item in news_items:
            analysis = item.get("gemini_analysis")
            if not isinstance(analysis, dict):
                continue
            names = [ProjectionEngine._normalize_name(value) for value in analysis.get("player_names", [])]
            if normalized_name in names and analysis.get("minutes_probability") is not None:
                try:
                    return max(0.0, min(1.0, float(analysis["minutes_probability"])))
                except (TypeError, ValueError):
                    continue
        minutes = float(player.get("minutes", 0) or 0)
        starts = float(player.get("starts", 0) or 0)
        if minutes <= 0:
            return 0.0
        historical_start_rate = starts / max(1.0, minutes / 90)
        return max(0.0, min(1.0, historical_start_rate))

    @staticmethod
    def _news_is_fresh(item, now, freshness_limit):
        timestamp = item.get("published_at_utc")
        if not timestamp:
            return False
        try:
            published = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            return False
        if published.tzinfo is None:
            return False
        age = now.astimezone(timezone.utc) - published.astimezone(timezone.utc)
        return timedelta(0) <= age <= freshness_limit

    @staticmethod
    def _normalize_name(value):
        return "".join(ch for ch in (value or "").lower() if ch.isalnum())

    @staticmethod
    def _captain_evidence(name, stats, player):
        values = stats.get(name, {})
        attacking = sum(float(values.get(key, 0) or 0) for key in ("xG", "xAG", "Gls", "Ast", "Sh", "SoT"))
        set_piece = sum(float(values.get(key, 0) or 0) for key in ("PK", "FK", "CK"))
        attacking += sum(float(player.get(key, 0) or 0) for key in ("goals", "assists", "shots", "key_passes"))
        set_piece += sum(float(player.get(key, 0) or 0) for key in ("penalties_order", "corners_order", "direct_freekicks_order"))
        return attacking, set_piece

    @staticmethod
    def _player_goal_probability(player, odds):
        player_name = ProjectionEngine._normalize_name(player.get("name") or f"{player.get('first_name', '')} {player.get('second_name', '')}")
        probabilities = [
            float(item.get("probability", 0) or 0)
            for item in odds
            if ProjectionEngine._normalize_name(item.get("player")) == player_name
        ]
        return max(probabilities, default=0.0)

    @staticmethod
    def _fixture_clean_sheet_probability(fixtures, team_id, gameweek):
        values = []
        for fixture in fixtures:
            if fixture.get("event") != gameweek:
                continue
            key = "team_h_clean_sheet_probability" if fixture.get("team_h") == team_id else "team_a_clean_sheet_probability" if fixture.get("team_a") == team_id else None
            if key and fixture.get(key) is not None:
                values.append(max(0.0, min(1.0, float(fixture[key]))))
        if not values:
            return None
        return round(1 - __import__("math").prod(1 - value for value in values), 4)


Projections = ProjectionEngine