class ChipsOptimizer:
    def __init__(self, players=None, bench=None, free_hit_gain=0.0, wildcard_gain=0.0, available=None, minimum_gain=4.0, all_players=None, budget=None, free_hit_squad=None, wildcard_squad=None):
        self.players = list(players or [])
        self.bench = list(bench or [])
        self.free_hit_gain = float(free_hit_gain)
        self.wildcard_gain = float(wildcard_gain)
        self.available = set({"TC", "BB", "FH", "WC"} if available is None else available)
        self.minimum_gain = minimum_gain
        self.all_players = list(all_players or [])
        self.budget = budget
        self.free_hit_squad = free_hit_squad
        self.wildcard_squad = wildcard_squad

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
        best_chip = max(eligible, key=lambda chip: eligible[chip]["expected_gain"], default=None)
        threshold = self._dynamic_threshold(best_chip, eligible.get(best_chip, {}).get("expected_gain", 0.0)) if best_chip else 0.0
        if best_chip and eligible[best_chip]["expected_gain"] < threshold:
            best_chip = None
        if best_chip:
            eligible[best_chip]["expected_gain"] = round(eligible[best_chip]["expected_gain"], 2)
        recommendation = eligible.get(best_chip)
        if recommendation:
            recommendation["reason"] = f"the dynamic model values this chip at {recommendation['expected_gain']:.1f} points, above the scenario-adjusted threshold of {threshold:.1f}"
        else:
            recommendation = {"expected_gain": 0.0, "target": None, "reason": "no available chip clears the dynamic expected-value threshold"}
        return {"use_chip": best_chip, "best_chip": best_chip, "opportunities": eligible, "recommendation": recommendation}

    def _dynamic_threshold(self, chip, gain):
        if chip is None:
            return 0.0
        baseline = float(self.minimum_gain)
        if chip == "WC":
            return max(1.5, baseline * 0.65)
        if chip == "FH":
            return max(1.25, baseline * 0.5)
        if chip == "TC":
            return max(1.0, baseline * 0.35)
        if chip == "BB":
            return max(1.0, baseline * 0.4)
        return max(0.0, baseline)

    def _dynamic_wc_value(self):
        current = sum(self._points(player) for player in self.players)
        if self.wildcard_squad and self.wildcard_squad.get("starting_xi"):
            proposed = sum(self._points(player, "wildcard_expected_points") for player in self.wildcard_squad["starting_xi"])
        elif self.all_players and self.budget is not None:
            squad = self.build_best_squad(self.all_players, self.budget, "wildcard_expected_points")
            if squad:
                starters, _ = self.select_lineup(squad, "wildcard_expected_points")
                proposed = sum(self._points(player, "wildcard_expected_points") for player in starters)
            else:
                proposed = current
        else:
            proposed = current
        delta = max(0.0, proposed - current)
        if delta <= 0:
            return 0.0
        relative_gain = delta / max(1.0, current)
        if relative_gain > 3.5:
            return 0.0
        transfer_hit_savings = 4.0
        time_decay_value = 2.0
        dynamic_value = delta * 0.18 + transfer_hit_savings + time_decay_value
        return round(min(dynamic_value, 18.0), 2)

    def _dynamic_fh_value(self):
        current = sum(self._points(player) for player in self.players)
        if self.free_hit_squad and self.free_hit_squad.get("starting_xi"):
            proposed = sum(self._points(player) for player in self.free_hit_squad["starting_xi"])
        elif self.all_players and self.budget is not None:
            squad = self.build_best_squad(self.all_players, self.budget)
            if squad:
                starters, _ = self.select_lineup(squad)
                proposed = sum(self._points(player) for player in starters)
            else:
                proposed = current
        else:
            proposed = current
        delta = max(0.0, proposed - current)
        if delta <= 0:
            return 0.0
        relative_gain = delta / max(1.0, current)
        if relative_gain > 2.0:
            return 0.0
        return round(min(delta * 0.22 + 2.0, 14.0), 2)

    def _dynamic_tc_value(self, captain):
        if captain is None:
            return 0.0
        base = self._points(captain)
        double_gameweek_bonus = 0.6 if any(player.get("team") == captain.get("team") for player in self.players) else 0.0
        return round(max(0.0, base + double_gameweek_bonus), 2)

    def _dynamic_bb_value(self):
        if not self.bench:
            return 0.0
        value = sum(self._points(player) for player in self.bench)
        return round(min(value, 12.0), 2)

    def _chip_squad(self, score_field="expected_points", lineup_score_field="expected_points"):
        if not self.all_players or self.budget is None:
            return None
        squad = self.build_best_squad(self.all_players, self.budget, score_field)
        if len(squad) != 15:
            return None
        starters, bench = self.select_lineup(squad, lineup_score_field)
        captain = max(starters, key=lambda player: self._points(player, "expected_points"), default=None)
        vice = max((player for player in starters if player != captain), key=lambda player: self._points(player, "expected_points"), default=None)
        return {"players": squad, "starting_xi": starters, "bench": bench, "captain": captain, "vice_captain": vice}

    def build_chip_squad(self, score_field="expected_points"):
        return self._chip_squad(score_field, "expected_points")

    @classmethod
    def build_best_squad(cls, players, budget, score_field="expected_points"):
        quotas = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
        selected = []
        club_counts = {}
        remaining_budget = float(budget)
        for position, quota in quotas.items():
            options = sorted((player for player in players if player.get("position") == position), key=lambda player: float(player.get("price", 0)))
            for player in options:
                if len([item for item in selected if item.get("position") == position]) >= quota:
                    break
                club = player.get("team")
                price = float(player.get("price", 0))
                if club_counts.get(club, 0) >= 3 or price > remaining_budget:
                    continue
                selected.append(player)
                club_counts[club] = club_counts.get(club, 0) + 1
                remaining_budget -= price
        selected_ids = {player["id"] for player in selected}
        for candidate in sorted(players, key=lambda player: cls._points(player, score_field), reverse=True):
            if candidate["id"] in selected_ids:
                continue
            position = candidate.get("position")
            current_options = [player for player in selected if player.get("position") == position]
            if not current_options:
                continue
            outgoing = min(current_options, key=lambda player: cls._points(player, score_field))
            candidate_price = float(candidate.get("price", 0))
            outgoing_price = float(outgoing.get("price", 0))
            candidate_club = candidate.get("team")
            outgoing_club = outgoing.get("team")
            if candidate_club != outgoing_club and club_counts.get(candidate_club, 0) >= 3:
                continue
            if candidate_price - outgoing_price > remaining_budget:
                continue
            selected.remove(outgoing)
            selected.append(candidate)
            selected_ids.remove(outgoing["id"])
            selected_ids.add(candidate["id"])
            remaining_budget -= candidate_price - outgoing_price
            if outgoing_club != candidate_club:
                club_counts[outgoing_club] -= 1
                club_counts[candidate_club] = club_counts.get(candidate_club, 0) + 1
        return selected

    @classmethod
    def select_lineup(cls, squad, score_field="expected_points"):
        starters = []
        for position, count in (("GKP", 1), ("DEF", 3), ("MID", 2), ("FWD", 1)):
            starters.extend(sorted((player for player in squad if player.get("position") == position), key=lambda player: cls._points(player, score_field), reverse=True)[:count])
        remaining = [player for player in squad if player not in starters]
        starters.extend(sorted(remaining, key=lambda player: cls._points(player, score_field), reverse=True)[:11 - len(starters)])
        bench = sorted((player for player in squad if player not in starters), key=lambda player: cls._points(player, score_field), reverse=True)
        return starters, bench

    @staticmethod
    def _points(player, score_field="expected_points"):
        return float(player.get(score_field, 0))


Chips = ChipsOptimizer