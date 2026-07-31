from __future__ import annotations

# Keyword-based policy-relevance classifier.
#
# Split into two lists so that a bare entity mention (e.g., "Fed" or "日銀")
# never triggers by itself — that's important because a central bank's own
# press feed mentions the entity in every item regardless of content
# ("BOJ Governor gives lecture on history" would otherwise be classified as
# policy). Action / topic phrases carry the real signal.

POLICY_ACTION_PHRASES: tuple[str, ...] = (
    # ─── English: monetary ───
    "interest rate", "rate hike", "rate cut", "rate decision", "policy rate",
    "basis point", "bps",
    "monetary policy", "quantitative easing", "quantitative tightening",
    "yield curve control", "ycc",
    "tapering", "hawkish", "dovish",
    "governing council", "monetary policy committee",
    # ─── English: fiscal / trade / currency ───
    "fiscal policy", "fiscal stimulus", "stimulus package", "bailout",
    "budget deficit", "supplementary budget", "spending bill",
    "tariff", "trade war", "sanctions",
    "currency intervention", "fx intervention", "yen intervention", "yuan intervention",
    "capital controls",
    # ─── Japanese: monetary ───
    "政策金利", "利上げ", "利下げ", "追加利上げ", "追加緩和",
    "金融緩和", "金融引き締め", "量的緩和", "量的引き締め",
    "金融政策", "金融政策決定", "決定会合",
    "イールドカーブ・コントロール", "長短金利操作",
    # ─── Japanese: fiscal / trade / currency ───
    "財政政策", "経済対策", "景気対策", "補正予算", "予算案",
    "為替介入", "通貨介入", "円買い介入",
    "関税", "経済制裁",
    # ─── Institutional investor flows ───
    "gpif", "portfolio rebalancing", "asset allocation change",
    "資産配分変更", "運用方針変更",
)

POLICY_ENTITY_PHRASES: tuple[str, ...] = (
    "central bank", "federal reserve", "the fed", "fomc",
    "ecb", "boj", "pboc", "bank of japan", "bank of england", "european central bank",
    "日銀", "日本銀行", "連邦準備", "中央銀行",
)

_POLICY_SOURCE_CATEGORIES = frozenset(
    {"policy", "central_bank", "news", "political_events", "institutional_investor"}
)


def score(text: str) -> tuple[int, int]:
    """Return (action_phrase_hits, entity_phrase_hits) — both case-insensitive."""
    lower = text.lower()
    actions = sum(1 for p in POLICY_ACTION_PHRASES if p.lower() in lower)
    entities = sum(1 for p in POLICY_ENTITY_PHRASES if p.lower() in lower)
    return actions, entities


def is_policy_relevant(text: str, source_category: str) -> bool:
    """Decide whether to trigger LLM policy-hypothesis generation.

    Institutional-investor feeds are curated to one entity's own communications
    (GPIF etc.) — trust the source and process every item. Otherwise require
    at least one action phrase. Bare entity mentions never trigger on their
    own — that's why entities are counted separately (see module docstring).
    """
    if source_category not in _POLICY_SOURCE_CATEGORIES:
        return False
    if source_category == "institutional_investor":
        return True
    actions, _entities = score(text)
    return actions >= 1
