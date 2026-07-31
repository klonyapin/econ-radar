from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import feedparser

from src.models import IngestedEvent, SourceDefinition

# Some feeds (Reddit especially) 403 the default python UA. Identify ourselves.
_USER_AGENT = "econ-radar/0.1 (https://github.com/klonyapin/econ-radar)"


def fetch(source: SourceDefinition, since: datetime | None = None) -> list[IngestedEvent]:
    """Fetch new items from an RSS/Atom feed.

    Returns items whose published/updated timestamp is strictly after ``since``.
    """
    if not source.url:
        return []
    parsed = feedparser.parse(source.url, agent=_USER_AGENT)
    events: list[IngestedEvent] = []
    for entry in parsed.entries:
        ts = _entry_timestamp(entry)
        if since and ts <= since:
            continue
        events.append(
            IngestedEvent(
                id=_stable_id(source.id, entry),
                ts=ts,
                source=source.id,
                url=entry.get("link"),
                title=entry.get("title", "(no title)"),
                body=entry.get("summary") or entry.get("description"),
            )
        )
    return events


def _stable_id(source_id: str, entry) -> str:
    key = entry.get("id") or entry.get("link") or entry.get("title", "")
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:{h}"


def _entry_timestamp(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        struct = entry.get(key)
        if struct:
            return datetime(*struct[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)
