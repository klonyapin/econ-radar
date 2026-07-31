"""Detect geopolitical BREAKING events (war, coup, disaster, assassination).

Fires only on Tier 1 phrases — combinations that are almost never used
metaphorically. "invasion" alone hits too many sports headlines
("Chelsea's midfield invasion"); "military invasion" or "侵攻" hits few.

To keep the LLM cost bounded, `is_breaking` returns a category tag which
main.py de-dupes on: only one BREAKING per (category, day). A 4-hour
Ukraine war news cycle won't fire 20 times; the first hit does.
"""

from __future__ import annotations

# Tier 1: multi-word phrases and unambiguous single terms.
# Categorized so we can de-dup per category per day.
BREAKING_KEYWORDS: dict[str, tuple[str, ...]] = {
    "war": (
        "declares war", "declared war", "war declared",
        "declaration of war",
        "military invasion", "ground invasion", "full-scale invasion",
        "nuclear strike", "nuclear attack", "nuclear detonation",
        "state of war", "state of emergency declared",
        "宣戦布告", "全面戦争", "武力侵攻",
    ),
    "military_action": (
        "airstrike hits", "missile strike hits", "missile attack on",
        "cruise missile launched",
        "ballistic missile launched",
        "military intervention",
        "空爆実施", "ミサイル攻撃", "軍事介入",
    ),
    "coup_political_upheaval": (
        "military coup", "coup d'état", "coup attempt",
        "declared martial law", "martial law imposed",
        "regime toppled", "overthrown by military",
        "government overthrown",
        "president resigns", "prime minister resigns",
        "cabinet resigns",
        "クーデター", "軍事クーデター", "戒厳令",
        "首相が辞任", "首相辞任", "大統領辞任",
        "内閣総辞職",
    ),
    "assassination_attack": (
        "assassinated", "assassination attempt", "assassination of",
        "shot dead", "shot to death",
        "terrorist attack", "terror attack",
        "mass casualty", "suicide bombing",
        "hostage taking", "hostage crisis",
        "暗殺", "銃撃で死亡", "テロ攻撃",
        "多数死亡", "人質事件",
    ),
    "natural_disaster": (
        "major earthquake", "magnitude 7", "magnitude 8", "magnitude 9",
        "tsunami warning", "tsunami alert",
        "super typhoon", "super hurricane", "category 5 hurricane",
        "volcanic eruption",
        "大地震", "大津波", "津波警報",
        "巨大地震", "火山大噴火", "スーパー台風",
    ),
    "financial_crisis": (
        "bank run", "bank collapse", "bank failure",
        "sovereign default", "debt default",
        "currency crisis", "peg abandoned",
        "flash crash", "market halted", "trading suspended",
        "取り付け騒ぎ", "銀行破綻", "デフォルト宣言",
        "通貨危機", "取引停止",
    ),
    "nuclear_pandemic": (
        "nuclear test conducted", "conducted nuclear test",
        "pandemic declared",
        "level 6 pandemic", "level 7 pandemic",
        "who declares global emergency",
        "核実験を実施", "パンデミック宣言",
    ),
}


def classify(text: str) -> str | None:
    """Return the BREAKING category tag if any Tier 1 phrase hits, else None."""
    lower = text.lower()
    for category, phrases in BREAKING_KEYWORDS.items():
        if any(p.lower() in lower for p in phrases):
            return category
    return None
