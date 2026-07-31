from __future__ import annotations

import os
import sys

from anthropic import Anthropic

_MODEL = "claude-sonnet-5"


def get_client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY env var not set")
    return Anthropic(api_key=api_key)


def call_text(system: str, user: str, max_tokens: int = 1024) -> str:
    """One-shot text completion. Returns the model's text response.

    In DRY_RUN=1 mode, prints the prompt and returns a placeholder — lets
    the pipeline run end-to-end without spending on API calls.
    """
    if os.environ.get("DRY_RUN") == "1":
        print(f"[DRY_RUN llm] user={user[:150]!r}", file=sys.stderr)
        return "[DRY_RUN placeholder response — set DRY_RUN=0 to invoke Anthropic]"

    client = get_client()
    msg = client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "".join(parts)
