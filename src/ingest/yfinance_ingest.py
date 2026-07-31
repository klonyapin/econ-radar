from __future__ import annotations

from datetime import datetime, timedelta

import yfinance as yf

from src.models import MetricDefinition


def fetch_series(
    metric: MetricDefinition, since: datetime | None = None
) -> list[tuple[datetime, float]]:
    """Fetch daily close prices for a yfinance ticker."""
    if not metric.source_id:
        return []
    start = since or (datetime.utcnow() - timedelta(days=365))
    ticker = yf.Ticker(metric.source_id)
    hist = ticker.history(start=start.strftime("%Y-%m-%d"), auto_adjust=False)
    if hist.empty:
        return []
    return [(idx.to_pydatetime(), float(row["Close"])) for idx, row in hist.iterrows()]
