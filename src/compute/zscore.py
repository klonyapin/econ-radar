from __future__ import annotations

import math
from typing import Sequence


def rolling_zscore(series: Sequence[float], window: int = 90) -> float | None:
    """Compute z-score of the most recent value against a trailing window.

    Uses the last ``window`` values (excluding the latest itself) to derive
    mean and stdev, then scores the latest value. Returns None if there is
    not enough history or stdev is 0.
    """
    if len(series) < window + 1:
        return None
    latest = series[-1]
    history = series[-(window + 1) : -1]
    mean = sum(history) / window
    var = sum((x - mean) ** 2 for x in history) / window
    stdev = math.sqrt(var)
    if stdev == 0:
        return None
    return (latest - mean) / stdev
