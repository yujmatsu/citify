"""ForecastEngine: 純 Python (numpy なし) で月別件数の移動平均 + 線形回帰 + 3 か月予測。

Reviewer High #2 反映:
    - slope 標準誤差を計算し、3 段階 confidence (high/medium/low) を判定
    - CV (stddev / mean) 大なら confidence="low" 強制
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .schema import (
    Confidence,
    ForecastPoint,
    ForecastSeries,
    MonthCount,
    TrendClassification,
)

# 予測 horizon (固定 3 ヶ月)
DEFAULT_HORIZON = 3
# 移動平均 window
MOVING_AVG_WINDOW = 3
# 線形回帰に使う直近月数
REGRESSION_WINDOW = 6
# 標準誤差 / slope の比率 (低いほど信頼性高、t 値概念)
# |slope| / se(slope) < 2.0 なら confidence="medium"
T_VALUE_THRESHOLD_MEDIUM = 2.0
# CV (stddev / mean) 大なら confidence="low" 強制
CV_THRESHOLD_LOW = 0.5

# Trend 分類閾値 (件/月)
SLOPE_SURGE = 1.5
SLOPE_INCREASING = 0.5
SLOPE_DECREASING = -0.5
SLOPE_CRASH = -1.5


@dataclass
class _RegressionResult:
    slope: float
    intercept: float
    se_slope: float  # 標準誤差


def moving_average(values: list[float], window: int = MOVING_AVG_WINDOW) -> list[float]:
    """中央値ベースの単純移動平均。短い series でも先頭は raw 値を返す。"""
    if not values:
        return []
    result: list[float] = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start : i + 1]
        result.append(sum(chunk) / len(chunk))
    return result


def linear_regression(values: list[float]) -> _RegressionResult:
    """単純線形回帰 (y = slope * x + intercept)、標準誤差付き。

    x = [0, 1, ..., n-1]、y = values
    slope = cov(x,y) / var(x)
    se(slope) = sqrt( sum((y - y_hat)^2) / (n-2) / sum((x - x_mean)^2) )
    n < 3 なら slope = 0, se = inf。
    """
    n = len(values)
    if n < 3:
        return _RegressionResult(
            slope=0.0, intercept=values[0] if values else 0.0, se_slope=float("inf")
        )

    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n

    var_x = sum((x - x_mean) ** 2 for x in xs)
    if var_x == 0:
        return _RegressionResult(slope=0.0, intercept=y_mean, se_slope=float("inf"))

    cov_xy = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    slope = cov_xy / var_x
    intercept = y_mean - slope * x_mean

    # 残差平方和 → 標準誤差
    rss = sum((values[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n))
    if n - 2 <= 0:
        se_slope = float("inf")
    else:
        mse = rss / (n - 2)
        se_slope = math.sqrt(mse / var_x) if mse > 0 else 0.0

    return _RegressionResult(slope=slope, intercept=intercept, se_slope=se_slope)


def classify_trend(slope: float) -> TrendClassification:
    """slope から 5 段階トレンド分類。"""
    if slope >= SLOPE_SURGE:
        return "surge"
    if slope >= SLOPE_INCREASING:
        return "increasing"
    if slope <= SLOPE_CRASH:
        return "crash"
    if slope <= SLOPE_DECREASING:
        return "decreasing"
    return "flat"


def compute_confidence(
    history_months: int,
    values: list[float],
    slope: float,
    se_slope: float,
) -> Confidence:
    """信頼度 3 段階 (high/medium/low)。

    Reviewer High #2:
        - history < 6 → "low"
        - CV (stddev / mean) > 0.5 → "low" 強制
        - |slope| / se(slope) < 2.0 → "medium" (t 値小、有意性弱)
        - 上記すべて満たさず → "high"
    """
    if history_months < 6:
        return "low"
    if len(values) < 2:
        return "low"

    mean = sum(values) / len(values)
    if mean > 0:
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        stddev = math.sqrt(variance)
        cv = stddev / mean
        if cv > CV_THRESHOLD_LOW:
            return "low"

    if se_slope > 0 and math.isfinite(se_slope):
        t_value = abs(slope) / se_slope
        if t_value < T_VALUE_THRESHOLD_MEDIUM:
            return "medium"

    return "high"


def _next_year_months(last_ym: str, horizon: int) -> list[str]:
    """'2026-03' のような ym から horizon ヶ月先の ym を生成。"""
    try:
        year, month = (int(x) for x in last_ym.split("-"))
    except ValueError:
        return [f"forecast_{i + 1}" for i in range(horizon)]
    out: list[str] = []
    for _ in range(horizon):
        month += 1
        if month > 12:
            month = 1
            year += 1
        out.append(f"{year:04d}-{month:02d}")
    return out


class ForecastEngine:
    """月別件数 → ForecastSeries 純計算 Engine (LLM 不要)。"""

    def forecast_series(
        self,
        monthly_counts: list[MonthCount],
        horizon: int = DEFAULT_HORIZON,
    ) -> ForecastSeries:
        """過去 N か月 → 未来 horizon か月予測。"""
        n = len(monthly_counts)
        if n == 0:
            return ForecastSeries(
                historical=[],
                forecast=[],
                trend_classification="flat",
                slope=0.0,
                slope_std_error=0.0,
                confidence="low",
                months_in_history=0,
            )

        values = [m.speech_count for m in monthly_counts]
        smoothed = moving_average(values, window=MOVING_AVG_WINDOW)

        # 線形回帰は直近 REGRESSION_WINDOW か月 (smoothed) を使う
        window_values = smoothed[-REGRESSION_WINDOW:] if n >= REGRESSION_WINDOW else smoothed
        reg = linear_regression(window_values)

        trend = classify_trend(reg.slope)
        confidence = compute_confidence(
            history_months=n,
            values=values,
            slope=reg.slope,
            se_slope=reg.se_slope,
        )

        # forecast を horizon 件生成 (clip 0+ & 上限 = last_smoothed * 3)
        last_smoothed = smoothed[-1] if smoothed else 0.0
        upper_cap = max(last_smoothed * 3.0, last_smoothed + 10.0)
        forecast_ym = _next_year_months(monthly_counts[-1].year_month, horizon)

        # 予測値: last_smoothed から線形外挿
        forecast_points: list[ForecastPoint] = []
        if confidence == "low" and n < 6:
            # データ不足時は forecast を空に
            forecast_points = []
        else:
            for i, ym in enumerate(forecast_ym):
                raw = last_smoothed + reg.slope * (i + 1)
                clipped = max(0.0, min(raw, upper_cap))
                forecast_points.append(
                    ForecastPoint(year_month=ym, speech_count=clipped, is_forecast=True)
                )

        return ForecastSeries(
            historical=list(monthly_counts),
            forecast=forecast_points,
            trend_classification=trend,
            slope=reg.slope,
            slope_std_error=reg.se_slope if math.isfinite(reg.se_slope) else 0.0,
            confidence=confidence,
            months_in_history=n,
        )
