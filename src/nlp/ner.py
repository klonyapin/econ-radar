from __future__ import annotations


def extract_entities(text: str) -> list[dict]:
    """Return list of {label, text} dicts for named entities.

    TODO: use spaCy (en_core_web_sm, ja_core_news_sm) once we ship it.
    For MVP, returns empty; policy detection still works via source category.
    """
    return []
