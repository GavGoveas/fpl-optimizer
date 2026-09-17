from __future__ import annotations

import math
from statistics import mean


class BacktestMetrics:
    """Leakage-free aggregate metrics for prediction/actual point pairs."""

    @staticmethod
    def evaluate(predictions, actuals):
        pairs = [(float(prediction), float(actual)) for prediction, actual in zip(predictions, actuals)]
        if not pairs:
            return {"count": 0, "mae": 0.0, "rmse": 0.0, "bias": 0.0, "correlation": 0.0}
        errors = [prediction - actual for prediction, actual in pairs]
        mae = mean(abs(error) for error in errors)
        rmse = math.sqrt(mean(error * error for error in errors))
        prediction_mean = mean(prediction for prediction, _ in pairs)
        actual_mean = mean(actual for _, actual in pairs)
        covariance = sum((prediction - prediction_mean) * (actual - actual_mean) for prediction, actual in pairs)
        prediction_variance = sum((prediction - prediction_mean) ** 2 for prediction, _ in pairs)
        actual_variance = sum((actual - actual_mean) ** 2 for _, actual in pairs)
        correlation = covariance / math.sqrt(prediction_variance * actual_variance) if prediction_variance and actual_variance else 0.0
        return {"count": len(pairs), "mae": round(mae, 4), "rmse": round(rmse, 4), "bias": round(mean(errors), 4), "correlation": round(correlation, 4)}

    @staticmethod
    def walk_forward(records, predictor):
        results = []
        for record in sorted(records, key=lambda item: item.get("gameweek", 0)):
            prediction = predictor(record)
            results.append({"gameweek": record.get("gameweek"), "prediction": prediction, "actual": record["actual"]})
        metrics = BacktestMetrics.evaluate([item["prediction"] for item in results], [item["actual"] for item in results])
        return {"metrics": metrics, "records": results}
