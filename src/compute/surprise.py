from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.compute.zscore import rolling_zscore
from src.models import MetricDefinition


@dataclass
class SurpriseSignal:
    metric_id: str
    ts: datetime
    value: float
    zscore: float


def detect(
    metric: MetricDefinition,
    timeseries: list[tuple[datetime, float]],
    window: int = 90,
) -> SurpriseSignal | None:
    """Return a SurpriseSignal if the latest point exceeds the metric's threshold."""
    threshold = metric.surprise_threshold_zscore
    if threshold is None or not timeseries:
        return None
    values = [v for _, v in timeseries]
    z = rolling_zscore(values, window=window)
    if z is None:
        return None
    if abs(z) < threshold:
        return None
    ts, val = timeseries[-1]
    return SurpriseSignal(metric_id=metric.id, ts=ts, value=val, zscore=z)
