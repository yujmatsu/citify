"""CostAnomalyDetector: 純 Python (numpy なし) で日次 cost data から異常検知 (Plan CC)。

Plan Z forecast engine と同じ純計算パターン。
z-score + spike_ratio + drift 方向 (slope 符号、Reviewer Medium #5) で 4 種分類。
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict

from .schema import (
    AnomalyType,
    CostAnomaly,
    CostObservation,
    Severity,
)

logger = logging.getLogger(__name__)

# 異常判定閾値
SPIKE_Z_SCORE = 2.0  # 過去 7 日平均から 2σ 以上離れたら spike
SPIKE_RATIO = 1.5  # baseline の 1.5x 超えたら spike
DRIFT_CV = 0.3  # 変動係数 > 0.3 で drift 判定
BASELINE_WINDOW = 7  # 7 日間 baseline

# Severity 分類 (spike_ratio から)
SEVERITY_CRITICAL = 3.0
SEVERITY_HIGH = 2.0
SEVERITY_MEDIUM = 1.5


def classify_severity(spike_ratio: float) -> Severity:
    """spike_ratio から severity 4 段階。"""
    if spike_ratio >= SEVERITY_CRITICAL:
        return "critical"
    if spike_ratio >= SEVERITY_HIGH:
        return "high"
    if spike_ratio >= SEVERITY_MEDIUM:
        return "medium"
    return "low"


def _baseline_stats(history: list[float]) -> tuple[float, float]:
    """過去 N 日の (avg, stddev)。"""
    if not history:
        return 0.0, 0.0
    avg = sum(history) / len(history)
    if len(history) < 2:
        return avg, 0.0
    variance = sum((v - avg) ** 2 for v in history) / len(history)
    stddev = math.sqrt(variance)
    return avg, stddev


def _slope_sign(values: list[float]) -> int:
    """直近 N 日の単純線形回帰 slope 符号 (+1: drift_up / -1: drift_down / 0: flat)。"""
    n = len(values)
    if n < 3:
        return 0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    var_x = sum((x - x_mean) ** 2 for x in xs)
    if var_x == 0:
        return 0
    cov = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    slope = cov / var_x
    if slope > 0.1:
        return 1
    if slope < -0.1:
        return -1
    return 0


class CostAnomalyDetector:
    """日次 cost 観測列から異常を抽出する純計算 Detector (LLM 不要)。"""

    def detect_anomalies(
        self,
        observations: list[CostObservation],
    ) -> list[CostAnomaly]:
        """observations を service 別に group → 各日の baseline 統計 → anomaly_type 分類。"""
        if not observations:
            return []

        # service 別に日付昇順で並べる
        by_service: dict[str, list[CostObservation]] = defaultdict(list)
        for obs in observations:
            by_service[obs.service].append(obs)

        anomalies: list[CostAnomaly] = []
        for service, series in by_service.items():
            series_sorted = sorted(series, key=lambda o: o.date)
            for i, obs in enumerate(series_sorted):
                history = [o.cost_jpy for o in series_sorted[max(0, i - BASELINE_WINDOW) : i]]
                if len(history) < 3:
                    # 過去 data 不足 → normal 扱い (baseline 0 でスキップでも OK だが
                    # demo seed の前半が見えるよう normal で記録)
                    anomalies.append(
                        CostAnomaly(
                            date=obs.date,
                            service=obs.service,
                            cost_jpy=obs.cost_jpy,
                            baseline_avg_7d=0.0,
                            baseline_stddev_7d=0.0,
                            z_score=0.0,
                            spike_ratio=0.0,
                            anomaly_type="normal",
                            severity="low",
                        )
                    )
                    continue

                avg, stddev = _baseline_stats(history)
                # ゼロ除算ガード
                z_score = (obs.cost_jpy - avg) / stddev if stddev > 0 else 0.0
                spike_ratio = obs.cost_jpy / avg if avg > 0 else 0.0
                cv = stddev / avg if avg > 0 else 0.0
                slope_sign = _slope_sign(history)

                # 分類 (spike > drift > normal の優先順)
                anomaly_type: AnomalyType
                if z_score > SPIKE_Z_SCORE or spike_ratio > SPIKE_RATIO:
                    anomaly_type = "spike"
                elif cv > DRIFT_CV and slope_sign > 0:
                    anomaly_type = "drift_up"
                elif cv > DRIFT_CV and slope_sign < 0:
                    anomaly_type = "drift_down"
                else:
                    anomaly_type = "normal"

                severity: Severity = (
                    classify_severity(spike_ratio) if anomaly_type != "normal" else "low"
                )

                anomalies.append(
                    CostAnomaly(
                        date=obs.date,
                        service=service,  # type: ignore[arg-type]
                        cost_jpy=obs.cost_jpy,
                        baseline_avg_7d=avg,
                        baseline_stddev_7d=stddev,
                        z_score=z_score,
                        spike_ratio=spike_ratio,
                        anomaly_type=anomaly_type,
                        severity=severity,
                    )
                )

        return anomalies


def detect_cross_service_pattern(anomalies: list[CostAnomaly]) -> str | None:
    """Reviewer Medium #4: 同日に複数 service で spike なら rule-based メッセージ。

    Plan F との差別化 (横断パターン認識)。
    """
    by_date: dict[str, set[str]] = defaultdict(set)
    for a in anomalies:
        if a.anomaly_type == "spike":
            by_date[a.date.isoformat()].add(a.service)

    # 同日 2+ service で spike を検出した日があるか
    multi_service_days = [(d, services) for d, services in by_date.items() if len(services) >= 2]
    if multi_service_days:
        # 最新の日付を 1 件提示
        latest_date, services = max(multi_service_days, key=lambda x: x[0])
        services_str = ", ".join(sorted(services))
        return (
            f"{latest_date} に {services_str} で同時に spike 検出。"
            f"deploy / マイグレーション / 一括ジョブ起因の可能性があります。"
        )

    return None
