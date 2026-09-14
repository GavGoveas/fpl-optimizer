class ChipsOptimizer:
    def __init__(self, players=None, bench=None, free_hit_gain=0.0, wildcard_gain=0.0, available=None, minimum_gain=4.0, all_players=None, budget=None):
        self.players = list(players or [])
        self.bench = list(bench or [])
        self.free_hit_gain = float(free_hit_gain)
        self.wildcard_gain = float(wildcard_gain)
        self.available = set({"TC", "BB", "FH", "WC"} if available is None else available)
        self.minimum_gain = minimum_gain
        self.all_players = list(all_players or [])
        self.budget = budget

    def recommend_chip_usage(self):
        captain = max(self.players, key=self._points, default=None)
        opportunities = {
            "TC": {"expected_gain": self._points(captain) if captain else 0.0, "target": captain.get("name") if captain else None},
            "BB": {"expected_gain": sum(self._points(player) for player in self.bench), "target": None},
            "FH": {"expected_gain": self.free_hit_gain, "target": None, "squad": self._chip_squad()},
            "WC": {"expected_gain": self.wildcard_gain, "target": None, "squad": self._chip_squad()},
        }
        eligible = {chip: value for chip, value in opportunities.items() if chip in self.available}
        best_chip = max(eligible, key=lambda chip: eligible[chip]["expected_gain"], default=None)
        if best_chip and eligible[best_chip]["expected_gain"] < self.minimum_gain:
            best_chip = None
        if best_chip:
            eligible[best_chip]["expected_gain"] = round(eligible[best_chip]["expected_gain"], 2)
        recommendation = eligible.get(best_chip)
        if recommendation:
            recommendation["reason"] = f"the proposed squad gains {recommendation['expected_gain']:.1f} points over your current starting XI, above the {self.minimum_gain:.1f} point threshold"
        else:
            recommendation = {"expected_gain": 0.0, "target": None, "reason": "no available chip clears the configured expected-gain threshold"}
        return {"use_chip": best_chip, "best_chip": best_chip, "opportunities": eligible, "recommendation": recommendation}

    def _chip_squad(self):
        if not self.all_players or self.budget is None:
            return None
        squad = self.build_best_squad(self.all_players, self.budget)
        starters, bench = self.select_lineup(squad)
        captain = max(starters, key=self._points, default=None)
        vice = max((player for player in starters if player != captain), key=self._points, default=None)
        return {"players": squad, "starting_xi": starters, "bench": bench, "captain": captain, "vice_captain": vice}

    def build_chip_squad(self):
        return self._chip_squad()

    @classmethod
    def build_best_squad(cls, players, budget):
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
        for candidate in sorted(players, key=cls._points, reverse=True):
            if candidate["id"] in selected_ids:
                continue
            position = candidate.get("position")
            current_options = [player for player in selected if player.get("position") == position]
            if not current_options:
                continue
            outgoing = min(current_options, key=cls._points)
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
    def select_lineup(cls, squad):
        starters = []
        for position, count in (("GKP", 1), ("DEF", 3), ("MID", 2), ("FWD", 1)):
            starters.extend(sorted((player for player in squad if player.get("position") == position), key=cls._points, reverse=True)[:count])
        remaining = [player for player in squad if player not in starters]
        starters.extend(sorted(remaining, key=cls._points, reverse=True)[:11 - len(starters)])
        bench = sorted((player for player in squad if player not in starters), key=cls._points, reverse=True)
        return starters, bench

    @staticmethod
    def _points(player):
        return float(player.get("expected_points", 0))


Chips = ChipsOptimizer