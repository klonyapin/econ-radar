from __future__ import annotations

from datetime import datetime

from src.llm.client import call_text
from src.models import Hypothesis, HypothesisVerdict, VerificationResult


def judge(
    hypothesis: Hypothesis,
    baseline_value: float,
    observed_value: float,
    baseline_ts: datetime,
    observed_ts: datetime,
) -> VerificationResult:
    """Machine-judge a hypothesis: numeric comparison → verdict + LLM reasoning."""
    if baseline_value == 0:
        pct = 0.0 if observed_value == 0 else float("inf")
    else:
        pct = (observed_value - baseline_value) / abs(baseline_value) * 100

    verdict = _classify(hypothesis, pct)
    note = (
        f"baseline={baseline_value} at {baseline_ts.date()}, "
        f"observed={observed_value} at {observed_ts.date()}, "
        f"change={pct:+.2f}%, threshold={hypothesis.magnitude_threshold_pct}%"
    )
    reasoning = _explain(hypothesis, verdict, pct)
    return VerificationResult(
        hypothesis=hypothesis,
        verdict=verdict,
        baseline_value=baseline_value,
        observed_value=observed_value,
        observed_pct_change=pct,
        machine_note=note,
        llm_reasoning=reasoning,
    )


def _classify(h: Hypothesis, pct: float) -> HypothesisVerdict:
    magnitude = abs(pct)
    if magnitude < h.magnitude_threshold_pct:
        # Predicted no_change → holds; predicted movement → rejected
        if h.direction.value == "no_change":
            return HypothesisVerdict.HOLDS
        return HypothesisVerdict.REJECTED

    up_directions = {"up", "widen"}
    down_directions = {"down", "narrow"}
    predicted_up = h.direction.value in up_directions
    predicted_down = h.direction.value in down_directions

    actual_up = pct > 0

    if predicted_up and actual_up:
        return HypothesisVerdict.HOLDS
    if predicted_down and not actual_up:
        return HypothesisVerdict.HOLDS
    return HypothesisVerdict.REJECTED


_SYSTEM = """あなたはマクロ経済アナリストです。
仮説とその機械判定結果を受け取り、なぜその結果になったか (holds なら追認、
rejected なら失敗理由の候補) を3文以内で説明してください。
教科書的な決まり文句ではなく、この期間に起きた具体的な出来事に紐付けること。
"""


def _explain(h: Hypothesis, verdict: HypothesisVerdict, pct: float) -> str:
    user = (
        f"仮説: {h.metric_id} が {h.direction.value} する ({h.horizon_months}ヶ月, "
        f"閾値 {h.magnitude_threshold_pct}%, 経路 {h.transmission_channel})\n"
        f"実測: {pct:+.2f}%\n"
        f"判定: {verdict.value}\n"
    )
    try:
        return call_text(_SYSTEM, user, max_tokens=512)
    except Exception as e:
        return f"(LLM reasoning unavailable: {e})"
