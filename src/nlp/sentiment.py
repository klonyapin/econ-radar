from __future__ import annotations


def score(text: str) -> float | None:
    """Return sentiment score in [-1, 1], or None if unavailable.

    TODO: swap in FinBERT (transformers) once we're OK with the model download.
    For MVP, we skip sentiment rather than shipping a bad rule-based scorer.
    """
    return None
