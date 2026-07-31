from __future__ import annotations

from datetime import datetime

from src.models import MetricDefinition, SourceDefinition


def fetch_positioning(
    source: SourceDefinition, metrics: list[MetricDefinition]
) -> dict[str, list[tuple[datetime, float]]]:
    """Fetch CFTC Commitments of Traders (financial futures, disaggregated) CSV.

    Returns {metric_id: [(ts, net_spec_position)]}.

    TODO: parse the CFTC disaggregated financial futures fixed-width CSV.
    Columns of interest per metric.source_id (CFTC contract code):
        - "M_Money_Positions_Long_All" - managed money long
        - "M_Money_Positions_Short_All" - managed money short
    net_spec = long - short
    """
    return {}
