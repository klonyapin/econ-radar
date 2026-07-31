from __future__ import annotations

from datetime import datetime

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.models import MetricDefinition, SourceDefinition

_SOCRATA_ENDPOINT = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
_TIMEOUT = 30
# Max ~2 years of weekly data per contract for solid z-score baselines.
_LIMIT = 4000


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _get_json(url: str, params: dict) -> list:
    resp = httpx.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_positioning(
    source: SourceDefinition, metrics: list[MetricDefinition]
) -> dict[str, list[tuple[datetime, float]]]:
    """Fetch CFTC TFF (Traders in Financial Futures) net Leveraged Money position.

    Returns {metric_id: [(ts, net_position)]} where net = lev_money_long - lev_money_short.

    Leveraged Money (hedge funds and similar) is the CFTC TFF category that
    corresponds most closely to speculative positioning; net swings here are
    the classic carry-trade positioning signal.
    """
    id_map: dict[str, str] = {}
    for m in metrics:
        if m.source_id:
            id_map[m.source_id] = m.id
    if not id_map:
        return {}

    codes_where = ", ".join(f"'{c}'" for c in id_map.keys())
    params = {
        "$where": f"cftc_contract_market_code in ({codes_where})",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(_LIMIT),
        "$select": (
            "cftc_contract_market_code,report_date_as_yyyy_mm_dd,"
            "lev_money_positions_long,lev_money_positions_short"
        ),
    }
    endpoint = source.endpoint or source.url or _SOCRATA_ENDPOINT

    rows = _get_json(endpoint, params)

    result: dict[str, list[tuple[datetime, float]]] = {}
    for row in rows:
        code = row.get("cftc_contract_market_code")
        metric_id = id_map.get(code)
        if not metric_id:
            continue
        try:
            long = int(row["lev_money_positions_long"])
            short = int(row["lev_money_positions_short"])
            raw_date = row["report_date_as_yyyy_mm_dd"]
            ts = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
        except (KeyError, ValueError, TypeError):
            continue
        result.setdefault(metric_id, []).append((ts, float(long - short)))

    for k in result:
        result[k].sort(key=lambda p: p[0])
    return result
