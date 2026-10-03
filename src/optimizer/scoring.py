from __future__ import annotations

from typing import Any

from src.models.rules import FPLRules


class ScoringSystem:
    """Compatibility facade over the centralized, versioned FPL scoring rules."""

    def __init__(self, rules: FPLRules | None = None):
        self.rules = rules or FPLRules(version="FPL-default")

    def calculate_points(self, player_type: str, actions: dict[str, Any]) -> float:
        aliases = {
            "goal": "goals",
            "assist": "assists",
            "penalty_save": "penalty_saves",
            "own_goal": "own_goals",
            "yellow_card": "yellow_cards",
            "red_card": "red_cards",
        }
        normalized = {aliases.get(key, key): value for key, value in actions.items()}
        return self.rules.score_player(player_type, normalized)

    def calculate_total_points(self, players: list[dict[str, Any]]) -> dict[Any, float]:
        return {
            player["id"]: self.calculate_points(player["type"], player["actions"])
            for player in players
        }
