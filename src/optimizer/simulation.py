from __future__ import annotations

from statistics import mean, median, pstdev


class PlayerPointSimulator:
    """Summarize model-supplied samples without inventing event outcomes."""

    def simulate(self, player):
        samples = player.get("simulation_samples")
        if not isinstance(samples, list) or not samples:
            return {"available": False, "source": None, "sample_count": 0}
        numeric_samples = sorted(float(value) for value in samples)
        return {
            "available": True,
            "source": player.get("simulation_source", "provided_scenarios"),
            "mean": round(mean(numeric_samples), 2),
            "median": round(median(numeric_samples), 2),
            "stddev": round(pstdev(numeric_samples), 2),
            "p10": self._percentile(numeric_samples, 0.10),
            "p25": self._percentile(numeric_samples, 0.25),
            "p50": self._percentile(numeric_samples, 0.50),
            "p75": self._percentile(numeric_samples, 0.75),
            "p90": self._percentile(numeric_samples, 0.90),
            "p95": self._percentile(numeric_samples, 0.95),
            "probability_0_plus": round(sum(value >= 0 for value in numeric_samples) / len(numeric_samples), 4),
            "probability_6_plus": round(sum(value >= 6 for value in numeric_samples) / len(numeric_samples), 4),
            "probability_10_plus": round(sum(value >= 10 for value in numeric_samples) / len(numeric_samples), 4),
            "probability_15_plus": round(sum(value >= 15 for value in numeric_samples) / len(numeric_samples), 4),
            "probability_20_plus": round(sum(value >= 20 for value in numeric_samples) / len(numeric_samples), 4),
            "sample_count": len(numeric_samples),
        }

    @staticmethod
    def _percentile(values, fraction):
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * fraction))))
        return round(values[index], 2)
