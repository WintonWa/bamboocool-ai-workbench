import math
from statistics import mean
from typing import Dict, List, Sequence, Tuple


MODEL_NAMES = ("seasonal_naive_4w", "trend_seasonal", "lifecycle_damped")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _weekday_factors(values: Sequence[float], weekdays: Sequence[int]) -> List[float]:
    overall = mean(values) if values else 1.0
    factors = []
    for weekday in range(7):
        subset = [value for value, day in zip(values, weekdays) if day == weekday]
        factors.append(clamp((mean(subset) / overall) if subset and overall else 1.0, 0.72, 1.32))
    return factors


def _linear_trend(values: Sequence[float]) -> Tuple[float, float]:
    if len(values) < 2:
        return (values[-1] if values else 0.0, 0.0)
    count = len(values)
    x_mean = (count - 1) / 2
    y_mean = mean(values)
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values)) / denominator
    return y_mean - slope * x_mean, slope


def _ewma(values: Sequence[float], alpha: float = 0.12) -> float:
    if not values:
        return 0.0
    current = values[0]
    for value in values[1:]:
        current = alpha * value + (1 - alpha) * current
    return current


def _predict_one(method: str, train: Sequence[float], train_weekdays: Sequence[int], target_weekday: int, horizon: int, lifecycle: str) -> float:
    if not train:
        return 0.0
    recent = list(train[-180:])
    recent_weekdays = list(train_weekdays[-180:])
    weekday_factors = _weekday_factors(recent, recent_weekdays)
    weekday = weekday_factors[target_weekday]
    if method == "seasonal_naive_4w":
        matches = [value for value, day in zip(reversed(recent), reversed(recent_weekdays)) if day == target_weekday][:8]
        return max(0.0, mean(matches) if matches else mean(recent[-28:]))
    if method == "trend_seasonal":
        normalized = [value / weekday_factors[day] for value, day in zip(recent, recent_weekdays)]
        intercept, slope = _linear_trend(normalized)
        trend_value = intercept + slope * (len(normalized) - 1 + horizon)
        return max(0.0, trend_value * weekday)
    level = _ewma(recent[-90:])
    recent28 = mean(recent[-28:]) if len(recent) >= 28 else level
    previous28 = mean(recent[-56:-28]) if len(recent) >= 56 else recent28
    daily_change = clamp((recent28 / previous28) ** (1 / 28) - 1 if previous28 > 0 else 0.0, -0.004, 0.005)
    if lifecycle == "衰退期":
        daily_change = min(daily_change, -0.00025)
    elif lifecycle in ("新品期", "成长期"):
        daily_change = max(daily_change, 0.0002)
    return max(0.0, level * ((1 + daily_change) ** horizon) * weekday)


def evaluate_models(values: Sequence[float], weekdays: Sequence[int], lifecycle: str, validation_days: int = 56) -> Tuple[str, Dict[str, Dict[str, float]]]:
    start = max(56, len(values) - validation_days)
    metrics: Dict[str, Dict[str, float]] = {}
    for method in MODEL_NAMES:
        actuals: List[float] = []
        predictions: List[float] = []
        for index in range(start, len(values)):
            prediction = _predict_one(method, values[:index], weekdays[:index], weekdays[index], 1, lifecycle)
            actuals.append(values[index])
            predictions.append(prediction)
        absolute_error = sum(abs(actual - predicted) for actual, predicted in zip(actuals, predictions))
        actual_total = sum(abs(value) for value in actuals)
        wape = absolute_error / actual_total if actual_total else 0.0
        bias = (sum(predictions) - sum(actuals)) / actual_total if actual_total else 0.0
        mae = absolute_error / len(actuals) if actuals else 0.0
        metrics[method] = {"wape": wape, "bias": bias, "mae": mae, "validation_days": len(actuals)}
    selected = min(MODEL_NAMES, key=lambda name: metrics[name]["wape"])
    return selected, metrics


def forecast_baseline(method: str, values: Sequence[float], weekdays: Sequence[int], future_weekdays: Sequence[int], lifecycle: str) -> List[float]:
    return [
        _predict_one(method, values, weekdays, weekday, horizon, lifecycle)
        for horizon, weekday in enumerate(future_weekdays, start=1)
    ]


def interval_ratio(model_wape: float, confidence: float) -> float:
    confidence_penalty = (1 - clamp(confidence, 0.3, 1.0)) * 0.18
    return clamp(model_wape * 1.35 + confidence_penalty, 0.10, 0.42)


def round2(value: float) -> float:
    return round(value + 1e-12, 2)
