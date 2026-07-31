"""Look-ahead for scheduled policy events (FOMC / BOJ / ECB / BOE).

Two roles:
1. Inject context into LLM prompts when a decision just landed or is imminent
   ("FOMC decision in 4h — expect elevated volatility"). This lets the LLM
   interpret market moves in the right frame.
2. Post a morning briefing to Discord listing what's in the next 48h.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

CALENDAR_PATH = Path(__file__).resolve().parent.parent / "config" / "policy_calendar.yaml"


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    name: str
    date: datetime      # timezone-aware UTC
    entity: str         # fed | boj | ecb | boe
    kind: str           # monetary_policy_decision | speech | minutes_release
    importance: str     # high | medium | low


@lru_cache(maxsize=1)
def load() -> list[CalendarEvent]:
    if not CALENDAR_PATH.exists():
        return []
    data = yaml.safe_load(CALENDAR_PATH.read_text()) or {}
    events = []
    for e in data.get("events", []) or []:
        events.append(
            CalendarEvent(
                id=e["id"],
                name=e["name"],
                date=_parse_ts(e["date_utc"]),
                entity=e["entity"],
                kind=e["kind"],
                importance=e.get("importance", "medium"),
            )
        )
    return sorted(events, key=lambda ev: ev.date)


def _parse_ts(v) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    raise ValueError(f"policy_calendar: cannot parse timestamp {v!r}")


def current_context(
    now: datetime | None = None, window_hours: int = 24
) -> Optional[str]:
    """Return a human-readable context string if a high-importance event is
    within ``window_hours`` of ``now`` (before or after). None otherwise.

    Meant for prepending to LLM prompts so interpretation has the right frame.
    """
    now = now or datetime.now(timezone.utc)
    lo = now - timedelta(hours=window_hours)
    hi = now + timedelta(hours=window_hours)

    relevant = [
        e for e in load()
        if e.importance == "high" and lo <= e.date <= hi
    ]
    if not relevant:
        return None

    lines = []
    for e in relevant:
        offset_h = (e.date - now).total_seconds() / 3600
        if offset_h > 0.5:
            lines.append(f"- {e.name}: {offset_h:+.1f}h から (予定 {e.date.isoformat()})")
        elif offset_h < -0.5:
            lines.append(f"- {e.name}: {-offset_h:.1f}h 前に発生 ({e.date.isoformat()})")
        else:
            lines.append(f"- {e.name}: 現在進行中 ({e.date.isoformat()})")
    return "\n".join(lines)


def upcoming(within_hours: int = 48, now: datetime | None = None) -> list[CalendarEvent]:
    """Return high-importance events happening in the next ``within_hours``."""
    now = now or datetime.now(timezone.utc)
    hi = now + timedelta(hours=within_hours)
    return [e for e in load() if e.importance == "high" and now <= e.date <= hi]
