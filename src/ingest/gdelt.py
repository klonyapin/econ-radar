from __future__ import annotations

from datetime import datetime

from src.models import IngestedEvent, SourceDefinition


def fetch(source: SourceDefinition, since: datetime | None = None) -> list[IngestedEvent]:
    """Fetch matching articles from GDELT 2.0 DOC 2 API.

    TODO: call source.endpoint with source.query as the ``query`` param,
    ``mode=ArtList``, ``format=json``, ``timespan`` derived from ``since``.
    """
    return []
