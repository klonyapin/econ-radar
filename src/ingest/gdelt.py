from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.models import IngestedEvent, SourceDefinition

# GDELT asks that clients space queries at least 5s apart per IP.
# We only call once per 15-min job so this is comfortable, but we still
# back off on 429 / 5xx in case of retries or contention.
_TIMEOUT = 30
_MAX_RECORDS = 50


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=5, min=5, max=30),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _get_json(url: str, params: dict[str, str]) -> dict:
    resp = httpx.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch(source: SourceDefinition, since: datetime | None = None) -> list[IngestedEvent]:
    """Fetch matching articles from GDELT 2.0 DOC 2.0 API (ArtList mode).

    Uses source.query as the search expression. When ``since`` is given,
    fetches articles seen after it; otherwise the last hour.
    """
    if not source.endpoint or not source.query:
        return []

    params: dict[str, str] = {
        "query": source.query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(_MAX_RECORDS),
        "sort": "datedesc",
    }
    if since:
        start = since.astimezone(timezone.utc)
        params["startdatetime"] = start.strftime("%Y%m%d%H%M%S")
        params["enddatetime"] = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    else:
        params["timespan"] = "1h"

    data = _get_json(source.endpoint, params)

    events: list[IngestedEvent] = []
    for art in data.get("articles", []) or []:
        ts = _parse_seendate(art.get("seendate"))
        if ts is None:
            continue
        if since and ts <= since:
            continue
        title = (art.get("title") or "").strip() or "(no title)"
        url = art.get("url") or None
        events.append(
            IngestedEvent(
                id=_stable_id(source.id, url or title),
                ts=ts,
                source=source.id,
                url=url,
                title=title,
                body=_metadata_body(art),
            )
        )
    return events


def _parse_seendate(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _stable_id(source_id: str, key: str) -> str:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:{h}"


def _metadata_body(art: dict) -> Optional[str]:
    parts = []
    if art.get("domain"):
        parts.append(f"domain={art['domain']}")
    if art.get("sourcecountry"):
        parts.append(f"country={art['sourcecountry']}")
    if art.get("language"):
        parts.append(f"lang={art['language']}")
    return " | ".join(parts) if parts else None
