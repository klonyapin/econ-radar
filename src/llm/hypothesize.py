from __future__ import annotations

import json
import os
import sys

from pydantic import TypeAdapter, ValidationError

from src.config_loader import load_metrics, load_theory_channels
from src.llm.client import call_text
from src.models import Hypothesis, IngestedEvent

_HYPOTHESES_ADAPTER = TypeAdapter(list[Hypothesis])

_SYSTEM = """あなたはマクロ経済アナリストです。
政策発表を受けて、その効果に関する検証可能な仮説を JSON 配列で返してください。
以下の厳格なスキーマに従うこと。自由記述禁止。

各仮説は必ず以下のフィールドを持つ:
- metric_id: 提供された追跡メトリクスのID (それ以外禁止)
- direction: "up" | "down" | "widen" | "narrow" | "no_change"
- horizon_months: 1-60 の整数
- magnitude_threshold_pct: この値 (%) 未満の変化は "変化なし" と判定する境界
- transmission_channel: 提供された伝達経路カタログのID (それ以外禁止)
- falsification_criterion: 反証条件の平易な説明

最大5つ、最も自信のある仮説のみ返すこと。
出力は JSON 配列のみ、前後にテキストを付けない。
"""


def generate_hypotheses(policy_event: IngestedEvent) -> list[Hypothesis]:
    if os.environ.get("DRY_RUN") == "1":
        print(
            f"[DRY_RUN hypothesize] would generate hypotheses for: {policy_event.title[:100]}",
            file=sys.stderr,
        )
        return []

    metrics = load_metrics()
    channels = load_theory_channels()

    metrics_list = "\n".join(
        f"- {m.id} ({m.category}): {m.name}" for m in metrics.values()
    )
    channels_list = "\n".join(
        f"- {c.id}: {c.name} — {c.description}" for c in channels.values()
    )

    user = f"""## 政策発表
タイトル: {policy_event.title}
発表時刻: {policy_event.ts.isoformat()}
本文: {policy_event.body or "(本文なし、タイトルのみから推論)"}

## 追跡メトリクス (metric_id はここから選択のみ)
{metrics_list}

## 伝達経路カタログ (transmission_channel はここから選択のみ)
{channels_list}

JSON 配列を返せ。
"""
    raw = call_text(_SYSTEM, user, max_tokens=2048)
    # strip potential ```json fences
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    try:
        parsed = json.loads(text)
        hypotheses = _HYPOTHESES_ADAPTER.validate_python(parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        raise RuntimeError(f"LLM produced invalid hypothesis JSON: {e}\n---\n{raw}")

    # Enforce catalog membership beyond Pydantic type validation.
    for h in hypotheses:
        if h.metric_id not in metrics:
            raise RuntimeError(f"LLM referenced unknown metric_id: {h.metric_id}")
        if h.transmission_channel not in channels:
            raise RuntimeError(
                f"LLM referenced unknown transmission_channel: {h.transmission_channel}"
            )
    return hypotheses
