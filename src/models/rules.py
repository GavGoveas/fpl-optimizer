from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from typing import Any


_POSITION_ALIASES = {
    "GKP": "goalkeeper",
    "GK": "goalkeeper",
    "GOALKEEPER": "goalkeeper",
    "DEF": "defender",
    "DEFENDER": "defender",
    "MID": "midfielder",
    "MIDFIELDER": "midfielder",
    "FWD": "forward",
    "FORWARD": "forward",
}

# Central fallback for the official baseline rules if the API omits scoring metadata.
# Provider-supplied values override this map and carry their source in version.
_DEFAULT_RULES: dict[str, Any] = {
    "appearance_1_59": 1,
    "appearance_60_plus": 2,
    "goalkeeper_goal": 10,
    "defender_goal": 6,
    "midfielder_goal": 5,
    "forward_goal": 4,
    "assist": 3,
    "goalkeeper_clean_sheet": 4,
    "defender_clean_sheet": 4,
    "midfielder_clean_sheet": 1,
    "forward_clean_sheet": 0,
    "goalkeeper_save_every": 3,
    "goalkeeper_save_points": 1,
    "penalty_save": 5,
    "penalty_miss": -2,
    "goal_conceded_every": 2,
    "goal_conceded_points": -1,
    "own_goal": -2,
    "yellow_card": -1,
    "red_card": -3,
    "bonus_points_per_bps_rank": 1,
    "max_free_transfers": 5,
    "initial_free_transfers": 1,
    "transfer_hit_cost": 4,
    "defensive_contribution_points": 2,
    "defensive_contribution_thresholds": {"defender": 10, "midfielder": 12, "forward": 12},
    "squad_quotas": {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3},
    "formation_minimums": {"DEF": 3, "MID": 2, "FWD": 1},
    "formation_maximums": {"DEF": 5, "MID": 5, "FWD": 3},
    "club_player_limit": 3,
}


@dataclass(frozen=True)
class FPLRules:
    version: str
    scoring: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_RULES))
    source: str = "central_default"
    scoring_source: str = "central_default"

    @classmethod
    def from_bootstrap(cls, bootstrap: dict[str, Any]) -> "FPLRules":
        values = dict(_DEFAULT_RULES)
        position_scoring: dict[str, dict[str, Any]] = {}
        squad_quotas = {}
        formation_minimums = {}
        formation_maximums = {}
        for position in bootstrap.get("element_types", []):
            key = _POSITION_ALIASES.get(str(position.get("singular_name_short", "")).upper())
            if key and isinstance(position.get("scoring"), dict):
                position_scoring[key] = position["scoring"]
            short = str(position.get("singular_name_short", "")).upper()
            if short in {"GKP", "DEF", "MID", "FWD"}:
                if position.get("squad_select") is not None:
                    squad_quotas[short] = int(position["squad_select"])
                if position.get("squad_min_play") is not None:
                    formation_minimums[short] = int(position["squad_min_play"])
                if position.get("squad_max_play") is not None:
                    formation_maximums[short] = int(position["squad_max_play"])
        scoring_rules = bootstrap.get("scoring_rules") or []
        if isinstance(scoring_rules, dict):
            scoring_rules = [dict(value, key=key) for key, value in scoring_rules.items() if isinstance(value, dict)]
        for rule in scoring_rules:
            key = rule.get("key")
            if key and rule.get("points") is not None:
                normalized = {
                    "assists": "assist",
                    "penalties_saved": "penalty_save",
                    "penalties_missed": "penalty_miss",
                    "own_goals": "own_goal",
                    "yellow_cards": "yellow_card",
                    "red_cards": "red_card",
                }.get(key, key)
                values[normalized] = rule["points"]
        configured = bootstrap.get("fpl_scoring")
        if isinstance(configured, dict):
            values.update(configured)
        season = bootstrap.get("game_settings", {}).get("season") or bootstrap.get("season")
        if not season:
            season_years = sorted({
                datetime.fromisoformat(str(event["deadline_time"]).replace("Z", "+00:00")).year
                for event in bootstrap.get("events", [])
                if event.get("deadline_time")
            })
            season = f"{season_years[0]}/{season_years[-1]}" if season_years else "unknown"
        if position_scoring:
            values["position_scoring"] = position_scoring
        settings = bootstrap.get("game_settings") or {}
        initial_ft = settings.get("initial_free_transfers")
        if initial_ft is not None:
            values["initial_free_transfers"] = int(initial_ft)
        max_ft = settings.get("max_free_transfers")
        if max_ft is None and settings.get("max_extra_free_transfers") is not None:
            max_ft = int(settings["max_extra_free_transfers"]) + int(values["initial_free_transfers"])
        if max_ft is not None:
            values["max_free_transfers"] = int(max_ft)
        if squad_quotas:
            values["squad_quotas"] = squad_quotas
        if formation_minimums:
            values["formation_minimums"] = {key: value for key, value in formation_minimums.items() if key != "GKP"}
        if formation_maximums:
            values["formation_maximums"] = {key: value for key, value in formation_maximums.items() if key != "GKP"}
        if settings.get("squad_team_limit") is not None:
            values["club_player_limit"] = int(settings["squad_team_limit"])
        source = "official_fpl_api" if squad_quotas or settings else "central_default"
        scoring_source = "official_fpl_api" if scoring_rules or configured or position_scoring else "central_default"
        fingerprint = sha256(json.dumps(values, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        version = f"FPL-{season}" if season != "unknown" else f"FPL-rules-{fingerprint}"
        return cls(version=version, scoring=values, source=source, scoring_source=scoring_source)

    @property
    def max_free_transfers(self) -> int:
        return max(1, int(self.scoring.get("max_free_transfers", _DEFAULT_RULES["max_free_transfers"])))

    @property
    def initial_free_transfers(self) -> int:
        return max(0, int(self.scoring.get("initial_free_transfers", _DEFAULT_RULES["initial_free_transfers"])))

    @property
    def transfer_hit_cost(self) -> int:
        return max(0, int(self.scoring.get("transfer_hit_cost", _DEFAULT_RULES["transfer_hit_cost"])))

    @property
    def squad_quotas(self) -> dict[str, int]:
        return dict(self.scoring.get("squad_quotas", _DEFAULT_RULES["squad_quotas"]))

    @property
    def formation_minimums(self) -> dict[str, int]:
        return dict(self.scoring.get("formation_minimums", _DEFAULT_RULES["formation_minimums"]))

    @property
    def formation_maximums(self) -> dict[str, int]:
        return dict(self.scoring.get("formation_maximums", _DEFAULT_RULES["formation_maximums"]))

    @property
    def club_player_limit(self) -> int:
        return int(self.scoring.get("club_player_limit", _DEFAULT_RULES["club_player_limit"]))

    def score_player(self, position: str, actions: dict[str, float]) -> float:
        role = _POSITION_ALIASES.get(position.upper(), position.lower())
        score = 0.0
        minutes = max(0.0, float(actions.get("minutes", 0) or 0))
        if minutes > 0:
            score += float(self.scoring["appearance_60_plus"] if minutes >= 60 else self.scoring["appearance_1_59"])
        role_scoring = self.scoring.get("position_scoring", {}).get(role, {})
        goal_points = role_scoring.get("goals_scored", self.scoring.get(f"{role}_goal", 0))
        clean_sheet_points = role_scoring.get("clean_sheets", self.scoring.get(f"{role}_clean_sheet", 0))
        score += float(actions.get("goals", 0) or 0) * float(goal_points)
        score += float(actions.get("assists", 0) or 0) * float(self.scoring.get("assist", 3))
        if minutes >= 60 and actions.get("clean_sheet"):
            score += float(clean_sheet_points)
        if role == "goalkeeper":
            score += int(float(actions.get("saves", 0) or 0) / max(1, int(self.scoring["goalkeeper_save_every"]))) * float(self.scoring["goalkeeper_save_points"])
            score += float(actions.get("penalty_saves", 0) or 0) * float(self.scoring["penalty_save"])
            score += float(actions.get("goals_conceded", 0) or 0) // max(1, int(self.scoring["goal_conceded_every"])) * float(self.scoring["goal_conceded_points"])
        elif role == "defender":
            score += float(actions.get("goals_conceded", 0) or 0) // max(1, int(self.scoring["goal_conceded_every"])) * float(self.scoring["goal_conceded_points"])
        score += float(actions.get("penalties_missed", 0) or 0) * float(self.scoring["penalty_miss"])
        score += float(actions.get("own_goals", 0) or 0) * float(self.scoring["own_goal"])
        score += float(actions.get("yellow_cards", 0) or 0) * float(self.scoring["yellow_card"])
        score += float(actions.get("red_cards", 0) or 0) * float(self.scoring["red_card"])
        score += float(actions.get("bonus", 0) or 0)
        thresholds = self.scoring.get("defensive_contribution_thresholds", {})
        threshold = thresholds.get(role)
        defensive_actions = sum(float(actions.get(key, 0) or 0) for key in ("clearances", "blocks", "interceptions", "tackles", "recoveries"))
        if threshold and defensive_actions >= float(threshold):
            score += float(self.scoring["defensive_contribution_points"])
        return score
