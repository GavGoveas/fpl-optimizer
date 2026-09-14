class ChipsOptimizer:
    def __init__(self, players=None, bench=None, free_hit_gain=0.0, wildcard_gain=0.0, available=None, minimum_gain=4.0):
        self.players = list(players or [])
        self.bench = list(bench or [])
        self.free_hit_gain = float(free_hit_gain)
        self.wildcard_gain = float(wildcard_gain)
        self.available = set({"TC", "BB", "FH", "WC"} if available is None else available)
        self.minimum_gain = minimum_gain

    def recommend_chip_usage(self):
        captain = max(self.players, key=self._points, default=None)
        opportunities = {
            "TC": {"expected_gain": self._points(captain) if captain else 0.0, "target": captain.get("name") if captain else None},
            "BB": {"expected_gain": sum(self._points(player) for player in self.bench), "target": None},
            "FH": {"expected_gain": self.free_hit_gain, "target": None},
            "WC": {"expected_gain": self.wildcard_gain, "target": None},
        }
        eligible = {chip: value for chip, value in opportunities.items() if chip in self.available}
        best_chip = max(eligible, key=lambda chip: eligible[chip]["expected_gain"], default=None)
        if best_chip and eligible[best_chip]["expected_gain"] < self.minimum_gain:
            best_chip = None
        if best_chip:
            eligible[best_chip]["expected_gain"] = round(eligible[best_chip]["expected_gain"], 2)
        recommendation = eligible.get(best_chip)
        if recommendation:
            recommendation["reason"] = f"projected gain is {recommendation['expected_gain']:.1f}, above the {self.minimum_gain:.1f} point threshold"
        else:
            recommendation = {"expected_gain": 0.0, "target": None, "reason": "no available chip clears the configured expected-gain threshold"}
        return {"use_chip": best_chip, "best_chip": best_chip, "opportunities": eligible, "recommendation": recommendation}

    @staticmethod
    def _points(player):
        return float(player.get("expected_points", 0))


Chips = ChipsOptimizer