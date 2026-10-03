from itertools import product
import warnings

from src.models.rules import FPLRules


class ChipsOptimizer:
    def __init__(self, players=None, bench=None, free_hit_gain=0.0, wildcard_gain=0.0, available=None, all_players=None, budget=None, free_hit_squad=None, wildcard_squad=None, future_opportunities=None, rules=None):
        self.players = list(players or [])
        self.bench = list(bench or [])
        self.free_hit_gain = float(free_hit_gain)
        self.wildcard_gain = float(wildcard_gain)
        self.available = set({"TC", "BB", "FH", "WC"} if available is None else available)
        self.all_players = list(all_players or [])
        self.budget = budget
        self.free_hit_squad = free_hit_squad
        self.wildcard_squad = wildcard_squad
        self.future_opportunities = future_opportunities
        self.rules = rules or FPLRules(version="FPL-default")

    def recommend_chip_usage(self):
        captain = max(self.players, key=self._points, default=None)
        opportunities = {
            "TC": {
                "expected_gain": self._dynamic_tc_value(captain),
                "target": captain.get("name") if captain else None,
            },
            "BB": {
                "expected_gain": self._dynamic_bb_value(),
                "target": None,
            },
            "FH": {
                "expected_gain": self._dynamic_fh_value(),
                "target": None,
                "squad": self.free_hit_squad or self._chip_squad(),
                "persistence": "one_gameweek_then_revert",
            },
            "WC": {
                "expected_gain": self._dynamic_wc_value(),
                "target": None,
                "squad": self.wildcard_squad or self._chip_squad("wildcard_expected_points"),
                "persistence": "permanent",
            },
        }
        eligible = {chip: value for chip, value in opportunities.items() if chip in self.available}
        if self.future_opportunities is None:
            for value in eligible.values():
                value["future_value_available"] = False
                value["net_value_now"] = None
            recommendation = {
                "expected_gain": 0.0,
                "target": None,
                "reason": "chip decision unavailable: future Gameweek opportunity scenarios are not available",
            }
            return {"use_chip": None, "best_chip": None, "decision_available": False, "opportunities": eligible, "recommendation": recommendation}

        for chip, value in eligible.items():
            future = self.future_opportunities.get(chip)
            if not future:
                value["future_value_available"] = False
                value["net_value_now"] = None
                continue
            best_future = max(float(scenario["expected_gain"]) for scenario in future)
            value["best_future_gameweek"] = max(future, key=lambda scenario: float(scenario["expected_gain"])).get("gameweek")
            value["best_future_value"] = round(best_future, 2)
            value["future_value_available"] = True
            value["net_value_now"] = round(float(value["expected_gain"]) - best_future, 2)

        comparable = {chip: value for chip, value in eligible.items() if value.get("future_value_available")}
        best_chip = max(comparable, key=lambda chip: comparable[chip]["net_value_now"], default=None)
        if best_chip is None or comparable[best_chip]["net_value_now"] <= 0:
            best_chip = None
        if best_chip:
            recommendation = dict(eligible[best_chip])
            recommendation["reason"] = (
                f"current incremental value {recommendation['expected_gain']:.2f} exceeds "
                f"best modeled future value {recommendation['best_future_value']:.2f} "
                f"by {recommendation['net_value_now']:.2f} points"
            )
        else:
            recommendation = {
                "expected_gain": 0.0,
                "target": None,
                "reason": "preserve chips: no available chip has positive value over its best modeled future opportunity",
            }
        return {"use_chip": best_chip, "best_chip": best_chip, "decision_available": True, "opportunities": eligible, "recommendation": recommendation}

    def _dynamic_wc_value(self):
        current = sum(self._points(player) for player in self.players)
        if self.wildcard_squad and self.wildcard_squad.get("starting_xi"):
            proposed = sum(self._points(player, "wildcard_expected_points") for player in self.wildcard_squad["starting_xi"])
        elif self.all_players and self.budget is not None:
            squad = self.build_best_squad(self.all_players, self.budget, "wildcard_expected_points", self.rules)
            if squad:
                starters, _ = self.select_lineup(squad, "wildcard_expected_points", self.rules)
                proposed = sum(self._points(player, "wildcard_expected_points") for player in starters)
            else:
                proposed = current
        else:
            proposed = current
        delta = max(0.0, proposed - current)
        return round(max(0.0, delta), 2)

    def _dynamic_fh_value(self):
        current = sum(self._points(player) for player in self.players)
        if self.free_hit_squad and self.free_hit_squad.get("starting_xi"):
            proposed = sum(self._points(player) for player in self.free_hit_squad["starting_xi"])
        elif self.all_players and self.budget is not None:
            squad = self.build_best_squad(self.all_players, self.budget, rules=self.rules)
            if squad:
                starters, _ = self.select_lineup(squad, rules=self.rules)
                proposed = sum(self._points(player) for player in starters)
            else:
                proposed = current
        else:
            proposed = current
        return round(max(0.0, self.free_hit_gain or proposed - current), 2)

    def _dynamic_tc_value(self, captain):
        if captain is None:
            return 0.0
        base = self._points(captain)
        availability = max(0.0, min(1.0, float(captain.get("availability", 1) or 0)))
        return round(max(0.0, base * availability), 2)

    def _dynamic_bb_value(self):
        if not self.bench:
            return 0.0
        bb_value = sum(self._points(player) for player in self.bench)
        normal_sub_value = self._expected_auto_sub_points()
        return round(max(0.0, bb_value - normal_sub_value), 2)

    def _expected_auto_sub_points(self):
        starters = self.players
        bench = self.bench
        if not starters or not bench:
            return 0.0
        start_probabilities = [self._play_probability(player) for player in starters]
        bench_probabilities = [self._play_probability(player) for player in bench]
        expected = 0.0
        for start_mask in product((False, True), repeat=len(starters)):
            start_probability = 1.0
            active_starters = []
            missing_outfield = 0
            for player, probability, active in zip(starters, start_probabilities, start_mask):
                start_probability *= probability if active else 1.0 - probability
                if active:
                    active_starters.append(player)
                elif player.get("position") != "GKP":
                    missing_outfield += 1
            if start_probability == 0:
                continue
            for bench_mask in product((False, True), repeat=len(bench)):
                bench_probability = 1.0
                for probability, active in zip(bench_probabilities, bench_mask):
                    bench_probability *= probability if active else 1.0 - probability
                if bench_probability == 0:
                    continue
                scenario_points = 0.0
                starter_gk_missing = not any(player.get("position") == "GKP" for player in active_starters)
                bench_gk = next((index for index, player in enumerate(bench) if player.get("position") == "GKP"), None)
                if starter_gk_missing and bench_gk is not None and bench_mask[bench_gk]:
                    scenario_points += self._conditional_points(bench[bench_gk], bench_probabilities[bench_gk])
                positions = {position: sum(player.get("position") == position for player in active_starters) for position in ("DEF", "MID", "FWD")}
                for index, (player, plays) in enumerate(zip(bench, bench_mask)):
                    if player.get("position") == "GKP" or not plays or missing_outfield <= 0:
                        continue
                    next_positions = dict(positions)
                    next_positions[player.get("position")] = next_positions.get(player.get("position"), 0) + 1
                    if next_positions.get("DEF", 0) < 3 or next_positions.get("MID", 0) < 2 or next_positions.get("FWD", 0) < 1:
                        continue
                    scenario_points += self._conditional_points(player, bench_probabilities[index])
                    positions = next_positions
                    missing_outfield -= 1
                expected += start_probability * bench_probability * scenario_points
        return expected

    @staticmethod
    def _play_probability(player):
        availability = max(0.0, min(1.0, float(player.get("availability", 1.0) or 0.0)))
        minutes = max(0.0, min(1.0, float(player.get("minutes_probability", 1.0) or 0.0)))
        return availability * minutes

    @staticmethod
    def _conditional_points(player, play_probability):
        if play_probability <= 0:
            return 0.0
        return max(0.0, float(player.get("expected_points", 0) or 0)) / play_probability

    def _chip_squad(self, score_field="expected_points", lineup_score_field="expected_points"):
        if not self.all_players or self.budget is None:
            return None
        squad = self.build_best_squad(self.all_players, self.budget, score_field, self.rules)
        if len(squad) != 15:
            return None
        starters, bench = self.select_lineup(squad, lineup_score_field, self.rules)
        captain = max(starters, key=self.captain_score, default=None)
        vice = max((player for player in starters if player != captain), key=self.captain_score, default=None)
        return {"players": squad, "starting_xi": starters, "bench": bench, "captain": captain, "vice_captain": vice}

    def build_chip_squad(self, score_field="expected_points"):
        return self._chip_squad(score_field, "expected_points")

    @classmethod
    def build_best_squad(cls, players, budget, score_field="expected_points", rules=None):
        rules = rules or FPLRules(version="FPL-default")
        quotas = rules.squad_quotas
        positions = tuple(quotas)
        optimized = cls._solve_milp(players, budget, score_field, rules)
        if optimized is not None:
            return optimized
        pools = {
            position: sorted(
                (player for player in players if player.get("position") == position and player.get("id") is not None),
                key=lambda player: cls._points(player, score_field),
                reverse=True,
            )
            for position in positions
        }
        if any(len(pools[position]) < quotas[position] for position in positions):
            return []

        best_score = float("-inf")
        best_squad = []
        selected = []
        selected_ids = set()
        position_counts = {position: 0 for position in positions}
        club_counts = {}

        def upper_bound(current_score, current_position, candidate_start):
            bound = current_score
            for position in positions:
                needed = quotas[position] - position_counts[position]
                if needed <= 0:
                    continue
                start_index = candidate_start if position == current_position else 0
                available = [
                    cls._points(player, score_field)
                    for player in pools[position][start_index:]
                    if player["id"] not in selected_ids
                ]
                if len(available) < needed:
                    return float("-inf")
                bound += sum(sorted(available, reverse=True)[:needed])
            return bound

        def search(position_index, candidate_start, spent, score):
            nonlocal best_score, best_squad
            if position_index >= len(positions):
                if score > best_score:
                    best_score = score
                    best_squad = list(selected)
                return
            position = positions[position_index]
            if position_counts[position] >= quotas[position]:
                search(position_index + 1, 0, spent, score)
                return
            if upper_bound(score, position, candidate_start) <= best_score:
                return
            pool = pools[position]
            needed_after_choice = quotas[position] - position_counts[position] - 1
            for index in range(candidate_start, len(pool)):
                player = pool[index]
                player_id = player["id"]
                club = player.get("team")
                price = float(player.get("price", 0) or 0)
                if player_id in selected_ids or spent + price > float(budget) + 1e-9:
                    continue
                if club is not None and club_counts.get(club, 0) >= rules.club_player_limit:
                    continue
                possible = sum(
                    option["id"] not in selected_ids and option["id"] != player_id
                    for option in pool[index + 1:]
                )
                if possible < needed_after_choice:
                    continue
                selected.append(player)
                selected_ids.add(player_id)
                position_counts[position] += 1
                if club is not None:
                    club_counts[club] = club_counts.get(club, 0) + 1
                search(position_index, index + 1, spent + price, score + cls._points(player, score_field))
                if club is not None:
                    club_counts[club] -= 1
                position_counts[position] -= 1
                selected_ids.remove(player_id)
                selected.pop()

        search(0, 0, 0.0, 0.0)
        return best_squad

    @classmethod
    def _solve_milp(cls, players, budget, score_field, rules):
        try:
            import numpy as np
            from scipy.optimize import Bounds, LinearConstraint, milp
        except ImportError:
            return None
        quotas = rules.squad_quotas
        eligible = [
            player for player in players
            if player.get("id") is not None
            and player.get("position") in quotas
            and float(player.get("price", 0) or 0) >= 0
        ]
        if len(eligible) < sum(quotas.values()):
            return []
        clubs = sorted({player.get("team") for player in eligible if player.get("team") is not None})
        rows = [[1.0] * len(eligible)]
        lower = [float(sum(quotas.values()))]
        upper = [float(sum(quotas.values()))]
        for position, quota in quotas.items():
            rows.append([1.0 if player.get("position") == position else 0.0 for player in eligible])
            lower.append(float(quota))
            upper.append(float(quota))
        for club in clubs:
            rows.append([1.0 if player.get("team") == club else 0.0 for player in eligible])
            lower.append(0.0)
            upper.append(float(rules.club_player_limit))
        rows.append([float(player.get("price", 0) or 0) for player in eligible])
        lower.append(0.0)
        upper.append(float(budget))
        try:
            result = milp(
                c=-np.asarray([cls._points(player, score_field) for player in eligible], dtype=float),
                integrality=np.ones(len(eligible), dtype=int),
                bounds=Bounds(np.zeros(len(eligible)), np.ones(len(eligible))),
                constraints=LinearConstraint(np.asarray(rows), np.asarray(lower), np.asarray(upper)),
                options={"presolve": True},
            )
        except Exception as error:
            warnings.warn(f"MILP squad solver failed ({type(error).__name__}); using exact branch-and-bound fallback", RuntimeWarning)
            return None
        if not result.success or result.x is None:
            warnings.warn(f"MILP squad solver returned {result.message}; using exact branch-and-bound fallback", RuntimeWarning)
            return None
        squad = [player for player, chosen in zip(eligible, result.x) if chosen >= 0.5]
        if len(squad) != sum(quotas.values()):
            warnings.warn("MILP squad solver returned an invalid cardinality; using exact branch-and-bound fallback", RuntimeWarning)
            return None
        return squad

    @classmethod
    def select_lineup(cls, squad, score_field="expected_points", rules=None):
        rules = rules or FPLRules(version="FPL-default")
        minimums = rules.formation_minimums
        best = None
        max_defenders = sum(player.get("position") == "DEF" for player in squad)
        max_midfielders = sum(player.get("position") == "MID" for player in squad)
        max_forwards = sum(player.get("position") == "FWD" for player in squad)
        maximums = rules.formation_maximums
        for defenders in range(int(minimums["DEF"]), min(max_defenders, int(maximums["DEF"])) + 1):
            for midfielders in range(int(minimums["MID"]), min(max_midfielders, int(maximums["MID"])) + 1):
                forwards = 10 - defenders - midfielders
                if forwards < int(minimums["FWD"]) or forwards > min(max_forwards, int(maximums["FWD"])):
                    continue
                selected = []
                for position, count in (("GKP", 1), ("DEF", defenders), ("MID", midfielders), ("FWD", forwards)):
                    selected.extend(sorted((player for player in squad if player.get("position") == position), key=lambda player: cls._points(player, score_field), reverse=True)[:count])
                if len(selected) != 11:
                    continue
                score = sum(cls._points(player, score_field) for player in selected)
                if best is None or score > best[0]:
                    best = (score, selected)
        starters = best[1] if best else []
        bench = sorted(
            (player for player in squad if player not in starters),
            key=lambda player: (player.get("position") == "GKP", -cls._points(player, score_field)),
        )
        return starters, bench

    @staticmethod
    def _points(player, score_field="expected_points"):
        return float(player.get(score_field, 0))

    @staticmethod
    def captain_score(player):
        distribution = player.get("distribution") or {}
        distribution_mean = distribution.get("mean")
        projected = float(player.get("expected_points", 0) or 0)
        if distribution_mean is None:
            return projected
        return (projected + float(distribution_mean)) / 2


Chips = ChipsOptimizer