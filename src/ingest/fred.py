from __future__ import annotations

import os
from datetime import datetime

import httpx

from src.models import MetricDefinition

FRED_ENDPOINT = "https://api.stlouisfed.org/fred/series/observations"


def fetch_series(
    metric: MetricDefinition, since: datetime | None = None
) -> list[tuple[datetime, float]]:
    """Fetch a FRED series and return list of (timestamp, value)."""
    if not metric.source_id:
        return []
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY env var not set")

    params: dict[str, str] = {
        "series_id": metric.source_id,
        "api_key": api_key,
        "file_type": "json",
    }
    if since:
        params["observation_start"] = since.strftime("%Y-%m-%d")

    resp = httpx.get(FRED_ENDPOINT, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    result: list[tuple[datetime, float]] = []
    for obs in data.get("observations", []):
        try:
            value = float(obs["value"])
        except (ValueError, KeyError):
            continue
        ts = datetime.strptime(obs["date"], "%Y-%m-%d")
        result.append((ts, value))
    return result
