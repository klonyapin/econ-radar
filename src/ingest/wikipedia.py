from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.models import IngestedEvent, SourceDefinition

_TIMEOUT = 30
_MIN_DIFF_BYTES = 500  # smaller edits are typo-level noise
_USER_AGENT = "econ-radar/0.1 (https://github.com/klonyapin/econ-radar)"


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
def _get_json(url: str, params: dict) -> dict:
    resp = httpx.get(
        url,
        params=params,
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
    )
    resp.raise_for_status()
    return resp.json()


def fetch(source: SourceDefinition, since: datetime | None = None) -> list[IngestedEvent]:
    """Scan watched Wikipedia pages for significant recent edits.

    The rationale: a burst of substantive edits to a policy-related page often
    precedes or accompanies real-world policy news. We filter to non-bot edits
    with a meaningful diff to cut typo-level noise.

    ``source.query`` is a pipe-separated list of URL-encoded page titles
    (e.g., "Federal_Reserve|Bank_of_Japan|Quantitative_easing").
    """
    if not source.endpoint or not source.query:
        return []
    cutoff = since or (datetime.now(timezone.utc) - timedelta(hours=24))
    titles = [t.strip() for t in source.query.split("|") if t.strip()]

    events: list[IngestedEvent] = []
    for title in titles:
        try:
            events.extend(_scan_page(source, title, cutoff))
        except Exception:
            # Silent skip: one bad page shouldn't kill the whole batch.
            continue
    return events


def _scan_page(
    source: SourceDefinition, title: str, cutoff: datetime
) -> list[IngestedEvent]:
    params = {
        "action": "query",
        "titles": title,
        "prop": "revisions",
        "rvlimit": "20",
        "rvprop": "timestamp|user|comment|size|ids",
        "format": "json",
        "formatversion": "2",
    }
    data = _get_json(source.endpoint, params)
    pages = data.get("query", {}).get("pages", []) or []
    if not pages:
        return []
    page = pages[0]
    revisions = page.get("revisions") or []
    if not revisions:
        return []

    events: list[IngestedEvent] = []
    for i, rev in enumerate(revisions):
        ts = _parse_ts(rev.get("timestamp"))
        if ts is None or ts <= cutoff:
            continue

        # Wikipedia stores absolute page byte-size per revision; diff = |Δsize|.
        prev_size = revisions[i + 1].get("size", 0) if i + 1 < len(revisions) else 0
        diff_bytes = abs(rev.get("size", 0) - prev_size)
        if diff_bytes < _MIN_DIFF_BYTES:
            continue

        user = rev.get("user", "") or ""
        if _looks_like_bot(user):
            continue

        page_title = page.get("title", title)
        comment = (rev.get("comment") or "").strip()
        events.append(
            IngestedEvent(
                id=_stable_id(source.id, f"{title}:{rev.get('revid')}"),
                ts=ts,
                source=source.id,
                url=f"https://en.wikipedia.org/wiki/{title}",
                title=f"[Wikipedia] {page_title} edited ({diff_bytes:+d}B) by {user}",
                body=comment[:500] if comment else None,
            )
        )
    return events


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _looks_like_bot(username: str) -> bool:
    return username.lower().endswith("bot")


def _stable_id(source_id: str, key: str) -> str:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:{h}"
