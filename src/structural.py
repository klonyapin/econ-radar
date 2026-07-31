"""Match BREAKING / analytical triggers to a knowledge base of
"how similar events historically flowed through markets" and inject that
into LLM prompts. Companion to policy_calendar.py and rag.py.

The point: raw event data + numbers are not enough. The LLM needs a
"playbook" to reason from — past comparable disasters/crises + which
sectors/actors typically move + which metrics to watch.

Facts live in config/structural_facts.yaml. Each fact declares
match_keywords / match_categories so we can route BREAKING triggers
to relevant facts without a semantic-embedding step.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_FACTS_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "structural_facts.yaml"
)


@dataclass(frozen=True)
class StructuralFact:
    id: str
    title: str
    match_keywords: tuple[str, ...]
    match_categories: tuple[str, ...]
    historical_analogs: tuple[str, ...]
    flow_through: tuple[str, ...]
    background: str | None
    related_metrics: tuple[str, ...]
    key_actors: tuple[str, ...]


@lru_cache(maxsize=1)
def load() -> list[StructuralFact]:
    if not _FACTS_PATH.exists():
        return []
    data = yaml.safe_load(_FACTS_PATH.read_text()) or {}
    facts = []
    for f in data.get("facts", []) or []:
        facts.append(
            StructuralFact(
                id=f["id"],
                title=f["title"],
                match_keywords=tuple(f.get("match_keywords") or []),
                match_categories=tuple(f.get("match_categories") or []),
                historical_analogs=tuple(f.get("historical_analogs") or []),
                flow_through=tuple(f.get("flow_through") or []),
                background=f.get("background"),
                related_metrics=tuple(f.get("related_metrics") or []),
                key_actors=tuple(f.get("key_actors") or []),
            )
        )
    return facts


def match(
    text: str,
    category: str | None = None,
    related_metric_ids: list[str] | None = None,
) -> list[StructuralFact]:
    """Return facts whose match_keywords / match_categories / related_metrics
    overlap with the incoming trigger.

    ``text`` — free-form (article title + body, or trigger summary)
    ``category`` — an internal category label like 'natural_disaster' or
                   'official:usgs_significant'
    ``related_metric_ids`` — metric ids present in the trigger (surprise case)
    """
    lower = text.lower()
    metric_set = set(related_metric_ids or [])
    matches = []
    for fact in load():
        score = 0
        if any(kw.lower() in lower for kw in fact.match_keywords):
            score += 2
        if category and category in fact.match_categories:
            score += 3
        if metric_set and any(m in metric_set for m in fact.related_metrics):
            score += 1
        if score:
            matches.append((score, fact))
    matches.sort(key=lambda t: -t[0])
    return [f for _, f in matches[:3]]


def format_for_prompt(facts: list[StructuralFact]) -> str:
    """Render matched facts as a Markdown-ish block for prompt injection.

    Emphasises historical analogs and flow_through — those are the "playbook"
    the LLM should reason from.
    """
    if not facts:
        return ""
    parts = ["## 過去の類似事象と市場への波及 (playbook)"]
    for f in facts:
        parts.append("")
        parts.append(f"### {f.title}")
        if f.historical_analogs:
            parts.append("**過去実例:**")
            for h in f.historical_analogs:
                parts.append(f"- {h}")
        if f.flow_through:
            parts.append("**フローの連鎖:**")
            for ft in f.flow_through:
                parts.append(f"- {ft}")
        if f.related_metrics:
            parts.append(f"**関連メトリクス:** {', '.join(f.related_metrics)}")
        if f.key_actors:
            parts.append(f"**主要アクター:** {', '.join(f.key_actors)}")
        if f.background:
            parts.append(f"**背景:** {f.background.strip()}")
    return "\n".join(parts)
