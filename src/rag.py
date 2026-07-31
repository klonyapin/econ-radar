"""Retrieve past verified policy events analogous to a new incoming event.

Injecting these into the hypothesis-generation prompt gives the LLM concrete
prior cases to reason from — "last time the Fed did X, our hypothesis was Y,
actual outcome was Z" — rather than pure theory.

Similarity is category overlap: each event's text is mapped to a set of
policy categories (rate_action / qe / fx_intervention / fiscal / trade / …),
and events sharing at least one category are candidates. This works across
vocabularies where literal substring search fails ("basis points" vs "bps",
"rate hike" vs "利上げ"). No embedding model is needed.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

# Vocabulary categories. Phrases that mean the same policy concept are
# grouped so that "rate hike" and "利上げ" match despite string mismatch.
PHRASE_CATEGORIES: dict[str, list[str]] = {
    "rate_action": [
        "rate hike", "rate cut", "rate decision", "policy rate",
        "basis point", "bps",
        "interest rate", "raises rates", "cuts rates", "rate rise",
        "利上げ", "利下げ", "追加利上げ", "政策金利", "金融政策決定", "決定会合",
    ],
    "qe": [
        "quantitative easing", "quantitative tightening", "tapering",
        "yield curve control", "ycc",
        "量的緩和", "量的引き締め", "追加緩和", "長短金利操作", "イールドカーブ・コントロール",
    ],
    "hawkish_dovish": [
        "hawkish", "dovish",
    ],
    "fx_intervention": [
        "currency intervention", "fx intervention", "yen intervention",
        "yuan intervention", "capital controls",
        "為替介入", "通貨介入", "円買い介入",
    ],
    "fiscal": [
        "fiscal policy", "fiscal stimulus", "stimulus package", "bailout",
        "budget deficit", "supplementary budget", "spending bill",
        "財政政策", "経済対策", "景気対策", "補正予算", "予算案",
    ],
    "trade": [
        "tariff", "trade war", "sanctions", "関税", "経済制裁",
    ],
    "institutional_flow": [
        "gpif", "portfolio rebalancing", "asset allocation change",
        "資産配分変更", "運用方針変更",
    ],
}

_MAX_ANALOGS = 3
_CANDIDATE_POOL = 200  # cap the DB fetch; policy_events grows slowly


def categorize(text: str) -> set[str]:
    """Return the set of PHRASE_CATEGORIES this text belongs to (may be empty)."""
    lower = text.lower()
    matched: set[str] = set()
    for cat, phrases in PHRASE_CATEGORIES.items():
        if any(p.lower() in lower for p in phrases):
            matched.add(cat)
    return matched


def find_analogs(conn: sqlite3.Connection, text: str) -> list[dict]:
    """Return past verified policy events sharing at least one category with
    ``text``, ranked by (# shared categories, recency)."""
    my_cats = categorize(text)
    if not my_cats:
        return []

    rows = conn.execute(
        "SELECT id, announced_at, description, hypotheses, verification_result "
        "FROM policy_events "
        "WHERE verified_at IS NOT NULL "
        "ORDER BY announced_at DESC LIMIT ?",
        (_CANDIDATE_POOL,),
    ).fetchall()

    scored: list[tuple[int, datetime, dict]] = []
    for r in rows:
        their_cats = categorize(r["description"])
        overlap = my_cats & their_cats
        if not overlap:
            continue
        try:
            hypotheses = json.loads(r["hypotheses"])
            verification = json.loads(r["verification_result"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        analog = {
            "id": r["id"],
            "announced_at": _format_ts(r["announced_at"]),
            "description": r["description"],
            "hypotheses": hypotheses,
            "verification": verification,
            "matched_categories": sorted(overlap),
        }
        # Rank primarily by overlap size, then by recency.
        ts = r["announced_at"] if isinstance(r["announced_at"], datetime) else datetime.min
        scored.append((len(overlap), ts, analog))

    scored.sort(key=lambda t: (-t[0], -t[1].timestamp() if t[1] != datetime.min else 0))
    return [item[2] for item in scored[:_MAX_ANALOGS]]


def format_for_prompt(analogs: list[dict]) -> str:
    """Format analogs as a Markdown-ish block for prompt injection.

    Focuses on hypothesis-verdict pairs so the LLM can see what worked and
    what didn't in past similar cases.
    """
    if not analogs:
        return ""

    lines = ["## 過去の類似政策と実測された効果"]
    for a in analogs:
        cats = ", ".join(a.get("matched_categories", []))
        lines.append("")
        lines.append(f"### {a['announced_at']}: {a['description']}  _(shared: {cats})_")
        for v in a.get("verification", []) or []:
            hyp = v.get("hypothesis", {})
            verdict = v.get("verdict", "unknown")
            metric_id = hyp.get("metric_id", "?")
            direction = hyp.get("direction", "?")
            channel = hyp.get("transmission_channel", "?")
            change = v.get("observed_pct_change")
            change_str = f"{change:+.2f}%" if isinstance(change, (int, float)) else "?"
            lines.append(
                f"- 仮説: `{metric_id}` が {direction} (経路 {channel}) → "
                f"**{verdict}** (実測 {change_str})"
            )
    return "\n".join(lines)


def _format_ts(v) -> str:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, str):
        return v[:10]
    return str(v)
