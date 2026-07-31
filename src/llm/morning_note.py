"""Generate a professional-analyst-voice morning/evening note.

Instead of firing per-event LLM alerts, this consolidates the last N hours
of surprises, policy events, calendar upcoming, and metric moves into a
single narrative note in the style of Marc Chandler / Fed Guy / 大和総研.

Style rules live in ``prompts/style_guide.md`` — the LLM is instructed to
read that file's rules as its system prompt.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config_loader import load_metrics
from src.llm.client import call_text
from src.policy_calendar import upcoming

_STYLE_GUIDE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "prompts" / "style_guide.md"
)

_LOOKBACK_HOURS = 18   # for morning note: cover overnight + previous session
_HORIZON_HOURS = 48    # for calendar upcoming


def generate_note(
    conn: sqlite3.Connection, mode: str = "morning", now: datetime | None = None
) -> str:
    """Compose a morning ('morning') or evening ('evening') macro note.

    Returns the LLM's text (with header). In DRY_RUN mode returns a stub.
    """
    if os.environ.get("DRY_RUN") == "1":
        print(f"[DRY_RUN morning_note] would generate {mode} note", file=sys.stderr)
        return f"[DRY_RUN {mode} note placeholder]"

    now = now or datetime.now(timezone.utc)
    lookback_since = now - timedelta(hours=_LOOKBACK_HOURS)

    context = _assemble_context(conn, lookback_since, now)
    mode_label = _classify_mode(context)

    system = _load_system_prompt(mode_label)
    user = _render_user_context(context, mode, mode_label, now)

    return call_text(system, user, max_tokens=1500)


def generate_breaking(
    conn: sqlite3.Connection,
    trigger_type: str,
    trigger_summary: str,
    now: datetime | None = None,
) -> str:
    """Compose a Mode-D BREAKING note reacting to a single high-severity event.

    ``trigger_type``: 'surprise' | 'policy' | 'geopolitical'
    ``trigger_summary``: 1-sentence description with the key numbers.
    """
    if os.environ.get("DRY_RUN") == "1":
        print(f"[DRY_RUN morning_note] would generate BREAKING for {trigger_summary[:80]}", file=sys.stderr)
        return f"[DRY_RUN BREAKING placeholder for {trigger_type}]"

    now = now or datetime.now(timezone.utc)
    lookback_since = now - timedelta(hours=6)  # tight window: what's happening RIGHT NOW
    context = _assemble_context(conn, lookback_since, now)

    system = _load_system_prompt("D")
    user = (
        f"# 現在: {now.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"# 発火: BREAKING ({trigger_type})\n\n"
        f"## トリガ\n{trigger_summary}\n\n"
        f"{_render_user_context(context, 'breaking', 'D', now)}\n\n"
        f"---\n上記の BREAKING イベントについて、Mode D の Few-shot 例に沿って "
        f"200-350 字で即時解釈を書け。lede は 'BREAKING:' で始めよ。"
    )
    return call_text(system, user, max_tokens=800)


# ────────────────────── context assembly ──────────────────────


def _assemble_context(
    conn: sqlite3.Connection, since: datetime, now: datetime
) -> dict:
    surprises = _recent_surprises(conn, since)
    policy_events = _recent_policy_events(conn, since)
    metric_snapshot = _latest_metric_snapshot(conn)
    upcoming_events = upcoming(within_hours=_HORIZON_HOURS, now=now)
    recent_news = _top_news(conn, since, limit=10)

    return {
        "surprises": surprises,
        "policy_events": policy_events,
        "metric_snapshot": metric_snapshot,
        "upcoming_events": upcoming_events,
        "recent_news": recent_news,
    }


def _recent_surprises(conn, since: datetime) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, metric_id, value, zscore, llm_interpretation "
        "FROM surprises WHERE ts >= ? ORDER BY ABS(zscore) DESC LIMIT 8",
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def _recent_policy_events(conn, since: datetime) -> list[dict]:
    rows = conn.execute(
        "SELECT announced_at, description, hypotheses FROM policy_events "
        "WHERE announced_at >= ? ORDER BY announced_at DESC LIMIT 6",
        (since,),
    ).fetchall()
    out = []
    for r in rows:
        try:
            hyp = json.loads(r["hypotheses"])
        except Exception:
            hyp = []
        out.append({
            "announced_at": r["announced_at"],
            "description": r["description"],
            "hypotheses": hyp,
        })
    return out


def _latest_metric_snapshot(conn) -> dict:
    """Latest value for each metric, plus 1-day and 7-day % change if available."""
    metrics = load_metrics()
    snapshot = {}
    for mid in metrics:
        latest = conn.execute(
            "SELECT ts, value FROM metrics WHERE metric_id = ? "
            "ORDER BY ts DESC LIMIT 1",
            (mid,),
        ).fetchone()
        if not latest:
            continue
        prior_1d = conn.execute(
            "SELECT value FROM metrics WHERE metric_id = ? AND ts < ? "
            "ORDER BY ts DESC LIMIT 1",
            (mid, latest["ts"]),
        ).fetchone()
        change_1d = None
        if prior_1d and prior_1d["value"]:
            change_1d = (latest["value"] - prior_1d["value"]) / abs(prior_1d["value"]) * 100
        snapshot[mid] = {
            "value": latest["value"],
            "ts": latest["ts"],
            "change_1d_pct": change_1d,
        }
    return snapshot


def _top_news(conn, since: datetime, limit: int = 10) -> list[dict]:
    """Recent central bank / policy items from events table."""
    rows = conn.execute(
        "SELECT ts, source, title, url FROM events "
        "WHERE ts >= ? AND source IN ("
        "  'fed_press', 'fed_monetary', 'ecb_press', 'boj_press', "
        "  'boe_news', 'boe_publications', 'kantei_press', 'mof_japan', "
        "  'whitehouse_briefings', 'bis_cbspeeches', 'bis_pressrels'"
        ") ORDER BY ts DESC LIMIT ?",
        (since, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ────────────────────── mode / prompt selection ──────────────────────


def _classify_mode(context: dict) -> str:
    """Pick a mode label so the LLM sees the right few-shot example.

    Mode labels match the sections in style_guide.md:
      A = 静穏, B = サプライズ日, C = 政策会合日, D = BREAKING (called separately)
    """
    imminent_meeting = any(
        abs((e.date - datetime.now(timezone.utc)).total_seconds()) <= 6 * 3600
        for e in context["upcoming_events"]
    )
    if imminent_meeting:
        return "C"
    if context["surprises"]:
        return "B"
    return "A"


def _load_system_prompt(mode_label: str) -> str:
    style = _STYLE_GUIDE_PATH.read_text()
    return (
        "あなたはマクロ経済ストラテジストです。以下のスタイルガイドを "
        "厳守してください。テンプレートを埋めるのではなく、実データを見て "
        "何を lede にすべきかをあなたが判断すること。\n\n"
        + style
        + f"\n\n---\n今回はモード **{mode_label}** で書いてください。"
        f" 対応する例が上のスタイルガイドの「モード {mode_label}」節にあります。"
    )


def _render_user_context(
    context: dict, mode: str, mode_label: str, now: datetime
) -> str:
    parts = [
        f"# 現在: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"# 発火: {mode} note (mode {mode_label})",
        "",
    ]

    if context["upcoming_events"]:
        parts.append("## 今後 48h の政策イベント")
        for e in context["upcoming_events"]:
            hrs = (e.date - now).total_seconds() / 3600
            parts.append(f"- {e.name}: {hrs:+.1f}h 後 ({e.date.isoformat()})")
        parts.append("")

    if context["surprises"]:
        parts.append("## 直近のサプライズ検知 (最新順)")
        for s in context["surprises"]:
            interp = (s.get("llm_interpretation") or "").strip().splitlines()
            interp_head = interp[0] if interp else "(no interp)"
            parts.append(
                f"- {s['metric_id']}: {s['value']} at {s['ts']}, "
                f"z={s['zscore']:+.2f}  ({interp_head[:100]})"
            )
        parts.append("")

    if context["policy_events"]:
        parts.append("## 直近の政策発表 + LLM生成仮説")
        for pe in context["policy_events"]:
            parts.append(f"- {pe['announced_at']}: {pe['description'][:120]}")
            for h in pe["hypotheses"][:3]:
                parts.append(
                    f"  仮説: {h.get('metric_id')} {h.get('direction')} "
                    f"in {h.get('horizon_months')}mo via {h.get('transmission_channel')}"
                )
        parts.append("")

    if context["recent_news"]:
        parts.append("## 中銀・政府の直近発表 (見出しのみ)")
        for n in context["recent_news"]:
            parts.append(f"- [{n['source']}] {n['title'][:100]}")
        parts.append("")

    snap = context["metric_snapshot"]
    if snap:
        parts.append("## 主要メトリクス最新スナップショット")
        interesting = _pick_interesting_metrics(snap)
        for mid, s in interesting:
            chg = s.get("change_1d_pct")
            chg_str = f"{chg:+.2f}%" if chg is not None else "n/a"
            parts.append(f"- {mid}: {s['value']} (前値差 {chg_str})")
        parts.append("")

    parts.append(
        "---\n上記データから、日本語で morning/evening note を書け。"
        "スタイルガイドを厳守。lede は自分で選べ。全体で 400-700 字目安。"
    )
    return "\n".join(parts)


def _pick_interesting_metrics(snap: dict) -> list[tuple[str, dict]]:
    """Show at most ~15 metrics: prioritize large 1-day moves, then key rates/FX."""
    priority_ids = {
        "US_10Y", "US_2Y", "JP_10Y", "USDJPY", "EURUSD", "DXY",
        "SP500", "NIKKEI225", "VIX", "US_HY_SPREAD",
        "WTI_OIL", "GOLD", "COPPER", "BTC_USD", "USDCNY",
    }
    with_change = sorted(
        [
            (mid, s) for mid, s in snap.items()
            if s.get("change_1d_pct") is not None
        ],
        key=lambda x: abs(x[1]["change_1d_pct"]),
        reverse=True,
    )
    top_movers = with_change[:8]
    top_ids = {mid for mid, _ in top_movers}
    priority = [(mid, snap[mid]) for mid in priority_ids if mid in snap and mid not in top_ids]
    return top_movers + priority[: max(0, 15 - len(top_movers))]
