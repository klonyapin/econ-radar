from __future__ import annotations

from src.compute.surprise import SurpriseSignal
from src.config_loader import load_metrics, load_theory_channels
from src.llm.client import call_text

_SYSTEM = """あなたはマクロ経済アナリストです。
与えられた指標のサプライズ (統計的異常値) について、以下の形式で解釈を返してください:

1. **何が起きたか** (1文、数値ベース)
2. **なぜ起きた可能性が高いか** (直近の政策・出来事に紐付ける、最大3つの候補)
3. **理論的にどう波及するか** (提供された伝達経路カタログから最も関連するものを2つ選び、それぞれ短く説明)
4. **今後1-3ヶ月で見るべき指標** (追跡メトリクスから3つ)

推測ではなく、名指しできる理論と観測可能なメトリクスに紐付けること。「〜と思われる」的な曖昧表現は禁止。
"""


def interpret_surprise(signal: SurpriseSignal) -> str:
    metric = load_metrics().get(signal.metric_id)
    if not metric:
        return f"(unknown metric_id {signal.metric_id})"
    channels = load_theory_channels()
    catalog = "\n".join(
        f"- {c.id}: {c.name} — {c.description}" for c in channels.values()
    )
    metrics_list = "\n".join(f"- {m.id}: {m.name}" for m in load_metrics().values())
    user = f"""指標: {metric.name} ({metric.id})
最新値: {signal.value} {metric.unit}
z-score: {signal.zscore:.2f} (90日ローリングから)
発生時刻: {signal.ts.isoformat()}

## 伝達経路カタログ
{catalog}

## 追跡メトリクス
{metrics_list}
"""
    return call_text(_SYSTEM, user)
