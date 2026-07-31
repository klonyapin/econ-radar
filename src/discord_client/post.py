from __future__ import annotations

import os

import httpx

from src.config_loader import load_discord_channels

_DISCORD_MAX = 2000  # message length limit


def post(channel_key: str, content: str) -> None:
    """Post to a named Discord channel (mapping in config/discord.yaml)."""
    channels = load_discord_channels()
    env_var = channels.get(channel_key)
    if not env_var:
        raise ValueError(f"Unknown discord channel: {channel_key}")
    url = os.environ.get(env_var)
    if not url:
        # Silent skip in dev; a missing webhook shouldn't crash the pipeline.
        return
    for chunk in _split(content, _DISCORD_MAX):
        resp = httpx.post(url, json={"content": chunk}, timeout=15)
        resp.raise_for_status()


def _split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
