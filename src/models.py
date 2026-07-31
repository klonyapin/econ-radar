from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    WIDEN = "widen"
    NARROW = "narrow"
    NO_CHANGE = "no_change"


class HypothesisVerdict(str, Enum):
    HOLDS = "holds"
    PARTIAL = "partial"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class Hypothesis(BaseModel):
    """Structured claim about a policy's expected effect on a tracked metric.

    Fields are all mandatory to prevent the LLM from producing vague prose.
    metric_id and transmission_channel are cross-checked against
    config/metrics.yaml and config/theory_channels.yaml at load time
    (see llm.hypothesize).
    """

    model_config = ConfigDict(extra="forbid")

    metric_id: str
    direction: Direction
    horizon_months: int = Field(..., gt=0, le=60)
    magnitude_threshold_pct: float = Field(
        ...,
        gt=0,
        description="Below this magnitude of move (vs baseline) is treated as 'no meaningful change'",
    )
    transmission_channel: str
    falsification_criterion: str


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis: Hypothesis
    verdict: HypothesisVerdict
    baseline_value: Optional[float] = None
    observed_value: Optional[float] = None
    observed_pct_change: Optional[float] = None
    machine_note: str
    llm_reasoning: Optional[str] = None


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    category: str
    unit: str
    source: Optional[str] = None
    source_id: Optional[str] = None
    derived_from: Optional[list[str]] = None
    formula: Optional[str] = None
    derived: Optional[Literal["yoy_change", "mom_change"]] = None
    surprise_threshold_zscore: Optional[float] = None


class SourceDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: Literal["rss", "fred_api", "yfinance", "cot_csv", "gdelt"]
    category: str
    frequency: Literal["frequent", "daily", "weekly", "monthly"]
    url: Optional[str] = None
    endpoint: Optional[str] = None
    query: Optional[str] = None


class TransmissionChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    typical_lag_months: str


class IngestedEvent(BaseModel):
    """A single news / feed item."""

    model_config = ConfigDict(extra="forbid")

    id: str
    ts: datetime
    source: str
    url: Optional[str] = None
    title: str
    body: Optional[str] = None
    entities: list[dict] = Field(default_factory=list)
    sentiment: Optional[float] = None


class PolicyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    announced_at: datetime
    description: str
    source_event_id: Optional[str] = None
    hypotheses: list[Hypothesis]
    verified_at: Optional[datetime] = None
    verification_result: Optional[list[VerificationResult]] = None
