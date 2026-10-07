from __future__ import annotations

import math
import random
from statistics import mean, median


class PlayerPointSimulator:
    """Monte Carlo FPL point distributions from current player projections."""

    def __init__(self, simulations=10000, seed=None):
        self.simulations = max(100, int(simulations))
        self.seed = seed

    def simulate(self, player):
        rng = random.Random(self.seed if self.seed is not None else player.get("id", 0))
        expected = max(0.0, float(player.get("expected_points", 0) or 0))
        minutes_probability = max(0.0, min(1.0, float(player.get("minutes_probability", player.get("expected_minutes", 0) / 90) or 0)))
        samples = []
        for _ in range(self.simulations):
            minutes = 0 if rng.random() > minutes_probability else min(90, max(1, int(rng.gauss(float(player.get("expected_minutes", 60) or 60), 18))))
            appearance = 1 if minutes >= 60 else 1 if minutes >= 1 else 0
            attacking = max(0.0, expected - (2.0 if appearance else 0.0))
            goals = self._poisson(rng, attacking * 0.12 * minutes / 90)
            assists = self._poisson(rng, attacking * 0.08 * minutes / 90)
            clean_sheet = 1 if rng.random() < max(0.0, min(1.0, float(player.get("clean_sheet_probability", 0.25)))) and minutes >= 60 else 0
            bonus = min(3, self._poisson(rng, max(0.0, attacking * 0.12)))
            samples.append(float(appearance + (1 if minutes >= 60 else 0) + goals * (6 if player.get("position") in {"FWD", "MID"} else 6) + assists * 3 + clean_sheet * (4 if player.get("position") == "GKP" else 1) + bonus))
        samples.sort()
        return {
            "mean": round(mean(samples), 2),
            "median": round(median(samples), 2),
            "p10": self._percentile(samples, 0.10),
            "p25": self._percentile(samples, 0.25),
            "p75": self._percentile(samples, 0.75),
            "p90": self._percentile(samples, 0.90),
            "probability_6_plus": round(sum(value >= 6 for value in samples) / len(samples), 3),
            "probability_10_plus": round(sum(value >= 10 for value in samples) / len(samples), 3),
            "samples": len(samples),
        }

    @staticmethod
    def _poisson(rng, rate):
        if rate <= 0:
            return 0
        threshold = math.exp(-rate)
        count = 0
        product = 1.0
        while product > threshold:
            count += 1
            product *= rng.random()
        return count - 1

    @staticmethod
    def _percentile(values, fraction):
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * fraction))))
        return round(values[index], 2)
