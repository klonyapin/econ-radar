from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from src.models import MetricDefinition, SourceDefinition, TransmissionChannel

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@lru_cache(maxsize=1)
def load_metrics() -> dict[str, MetricDefinition]:
    data = yaml.safe_load((CONFIG_DIR / "metrics.yaml").read_text())
    return {m["id"]: MetricDefinition(**m) for m in data["metrics"]}


@lru_cache(maxsize=1)
def load_sources() -> dict[str, SourceDefinition]:
    data = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())
    return {s["id"]: SourceDefinition(**s) for s in data["sources"]}


@lru_cache(maxsize=1)
def load_theory_channels() -> dict[str, TransmissionChannel]:
    data = yaml.safe_load((CONFIG_DIR / "theory_channels.yaml").read_text())
    return {c["id"]: TransmissionChannel(**c) for c in data["transmission_channels"]}


@lru_cache(maxsize=1)
def load_discord_channels() -> dict[str, str]:
    """Returns {channel_key: env_var_name}."""
    data = yaml.safe_load((CONFIG_DIR / "discord.yaml").read_text())
    return dict(data["channels"])
