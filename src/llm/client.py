from __future__ import annotations

import os

from anthropic import Anthropic

_MODEL = "claude-sonnet-5"


def get_client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY env var not set")
    return Anthropic(api_key=api_key)


def call_text(system: str, user: str, max_tokens: int = 1024) -> str:
    """One-shot text completion. Returns the model's text response."""
    client = get_client()
    msg = client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "".join(parts)
