"""CLI entrypoint. Invoked by GitHub Actions workflows.

Usage:
    python -m src.main ingest-frequent
    python -m src.main ingest-daily
    python -m src.main ingest-weekly
    python -m src.main retrospective
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

from src import db
from src.compute import derived as derived_mod
from src.compute import surprise as surprise_mod
from src.config_loader import load_metrics, load_sources
from src.discord_client import post as discord_post
from src.ingest import cot as cot_ingest
from src.ingest import fred as fred_ingest
from src.ingest import gdelt as gdelt_ingest
from src.ingest import rss as rss_ingest
from src.ingest import wikipedia as wikipedia_ingest
from src.ingest import yfinance_ingest
from src.llm import hypothesize, interpret, retrospective
from src.llm import morning_note
from src.models import IngestedEvent, MetricDefinition
from src.nlp import breaking_classifier, policy_classifier
from src import policy_calendar, rag


# ────────────────────── generic helpers ──────────────────────


def _last_success(conn, job_name: str) -> datetime | None:
    row = conn.execute(
        "SELECT last_success_ts FROM job_runs WHERE job_name = ?", (job_name,)
    ).fetchone()
    if not row or not row["last_success_ts"]:
        return None
    return row["last_success_ts"]


def _mark_success(conn, job_name: str, ts: datetime) -> None:
    conn.execute(
        "INSERT INTO job_runs (job_name, last_success_ts) VALUES (?, ?) "
        "ON CONFLICT(job_name) DO UPDATE SET last_success_ts = excluded.last_success_ts",
        (job_name, ts),
    )
    conn.commit()


def _insert_event(conn, ev: IngestedEvent) -> bool:
    """Insert if new. Returns True if inserted, False if duplicate."""
    try:
        conn.execute(
            "INSERT INTO events (id, ts, source, url, title, body, entities, sentiment) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ev.id,
                ev.ts,
                ev.source,
                ev.url,
                ev.title,
                ev.body,
                json.dumps(ev.entities),
                ev.sentiment,
            ),
        )
        return True
    except Exception:
        return False


def _upsert_metric_points(
    conn, metric_id: str, source: str, points: list[tuple[datetime, float]]
) -> int:
    n = 0
    for ts, val in points:
        try:
            conn.execute(
                "INSERT INTO metrics (metric_id, ts, value, source) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(metric_id, ts) DO NOTHING",
                (metric_id, ts, val, source),
            )
            n += 1
        except Exception:
            pass
    return n


def _metric_series(conn, metric_id: str, limit: int = 200) -> list[tuple[datetime, float]]:
    rows = conn.execute(
        "SELECT ts, value FROM metrics WHERE metric_id = ? ORDER BY ts DESC LIMIT ?",
        (metric_id, limit),
    ).fetchall()
    return [(r["ts"], r["value"]) for r in reversed(rows)]


# ────────────────────── jobs ──────────────────────


def job_ingest_frequent() -> None:
    """15-min job: RSS + GDELT. Detect policy items → LLM hypotheses."""
    db.initialize()
    conn = db.get_connection()
    try:
        since = _last_success(conn, "ingest_frequent")
        sources = [s for s in load_sources().values() if s.frequency == "frequent"]

        for src in sources:
            try:
                if src.type == "rss":
                    events = rss_ingest.fetch(src, since=since)
                elif src.type == "gdelt":
                    events = gdelt_ingest.fetch(src, since=since)
                elif src.type == "wikipedia":
                    events = wikipedia_ingest.fetch(src, since=since)
                else:
                    continue
            except Exception as e:
                _log_error(f"fetch failed: {src.id}: {e}")
                continue

            for ev in events:
                if not _insert_event(conn, ev):
                    continue
                _post_raw(ev)
                combined_text = f"{ev.title} {ev.body or ''}"

                # Geopolitical BREAKING check (wars, coups, disasters, etc.)
                _check_geopolitical_breaking(conn, ev, combined_text)

                if policy_classifier.is_policy_relevant(combined_text, src.category):
                    _handle_policy_event(conn, ev)

        _mark_success(conn, "ingest_frequent", datetime.now(timezone.utc))
    finally:
        conn.close()


def job_ingest_daily() -> None:
    """Daily job: FRED + yfinance. Refresh components → derived → z-score → LLM."""
    db.initialize()
    _post_morning_briefing()

    conn = db.get_connection()
    try:
        metrics = list(load_metrics().values())
        components = [m for m in metrics if not m.derived_from]
        derived = [m for m in metrics if m.derived_from]

        # Pass 1: fetch all component metrics from their upstream sources.
        for metric in components:
            since = _metric_last_ts(conn, metric.id)
            try:
                if metric.source == "fred":
                    pts = fred_ingest.fetch_series(metric, since=since)
                elif metric.source == "yfinance":
                    pts = yfinance_ingest.fetch_series(metric, since=since)
                else:
                    continue
            except Exception as e:
                _log_error(f"metric fetch failed: {metric.id}: {e}")
                continue
            _upsert_metric_points(conn, metric.id, metric.source or "", pts)
            conn.commit()

        # Pass 2: recompute derived metrics from freshly-updated components.
        for metric in derived:
            try:
                derived_mod.refresh(conn, metric)
            except Exception as e:
                _log_error(f"derived refresh failed: {metric.id}: {e}")

        # Pass 3: surprise detection on both components and derived.
        for metric in metrics:
            _detect_and_post_surprise(conn, metric)

        _mark_success(conn, "ingest_daily", datetime.now(timezone.utc))
    finally:
        conn.close()


def job_ingest_weekly() -> None:
    """Weekly job: CFTC COT positioning."""
    db.initialize()
    conn = db.get_connection()
    try:
        cot_sources = [
            s for s in load_sources().values() if s.type == "cot"
        ]
        cot_metrics = [
            m for m in load_metrics().values() if m.source and m.source.startswith("cftc")
        ]
        for src in cot_sources:
            try:
                data = cot_ingest.fetch_positioning(src, cot_metrics)
            except Exception as e:
                _log_error(f"COT fetch failed: {src.id}: {e}")
                continue
            for metric_id, points in data.items():
                _upsert_metric_points(conn, metric_id, src.id, points)

        conn.commit()
        for m in cot_metrics:
            _detect_and_post_surprise(conn, m)

        _mark_success(conn, "ingest_weekly", datetime.now(timezone.utc))
    finally:
        conn.close()


def job_daily_briefing() -> None:
    """Consolidated 2x/day macro note in real-analyst voice.

    Mode is picked by JOB_MODE env var ('morning' or 'evening'). Pulls the
    last ~18h of surprises, policy events, and metric moves into a single
    narrative note using ``prompts/style_guide.md``.
    """
    mode = os.environ.get("JOB_MODE", "morning")
    db.initialize()
    conn = db.get_connection()
    try:
        try:
            note = morning_note.generate_note(conn, mode=mode)
        except Exception as e:
            _log_error(f"morning_note generation failed: {e}")
            return

        emoji = "🌅" if mode == "morning" else "🌇"
        now_utc = datetime.now(timezone.utc)
        header = f"{emoji} **{mode.upper()} note — {now_utc.strftime('%Y-%m-%d %H:%M UTC')}**"
        discord_post.post("policy", f"{header}\n\n{note}")
    finally:
        conn.close()


def job_retrospective() -> None:
    """Daily 01:00 UTC: verify policy hypotheses whose horizon has elapsed."""
    db.initialize()
    conn = db.get_connection()
    try:
        now = datetime.now(timezone.utc)
        rows = conn.execute(
            "SELECT id, announced_at, description, hypotheses FROM policy_events "
            "WHERE verified_at IS NULL"
        ).fetchall()
        for row in rows:
            hypotheses = [__hypothesis_from_dict(h) for h in json.loads(row["hypotheses"])]
            announced: datetime = row["announced_at"]
            max_horizon = max(h.horizon_months for h in hypotheses)
            if announced + timedelta(days=max_horizon * 30) > now:
                continue  # not yet due

            results = []
            for h in hypotheses:
                r = _verify(conn, h, announced)
                if r is not None:
                    results.append(r)
            if not results:
                continue

            conn.execute(
                "UPDATE policy_events SET verified_at = ?, verification_result = ? WHERE id = ?",
                (
                    now,
                    json.dumps([r.model_dump(mode="json") for r in results]),
                    row["id"],
                ),
            )
            conn.commit()
            _post_retrospective(row["id"], row["description"], results)
    finally:
        conn.close()


# ────────────────────── per-event helpers ──────────────────────


def _handle_policy_event(conn, ev: IngestedEvent) -> None:
    """Generate hypotheses via LLM, persist, post to #policy.

    Enriches the prompt with (a) upcoming/recent policy calendar context and
    (b) past verified analogs whose descriptions share action phrases.
    """
    try:
        analogs = rag.find_analogs(conn, f"{ev.title} {ev.body or ''}")
        analog_ctx = rag.format_for_prompt(analogs)
        hypotheses = hypothesize.generate_hypotheses(ev, analog_context=analog_ctx)
    except Exception as e:
        _log_error(f"hypothesis gen failed for {ev.id}: {e}")
        return
    if not hypotheses:
        return

    conn.execute(
        "INSERT INTO policy_events (id, announced_at, description, source_event_id, hypotheses) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
        (
            f"pe:{ev.id}",
            ev.ts,
            ev.title,
            ev.id,
            json.dumps([h.model_dump(mode="json") for h in hypotheses]),
        ),
    )
    conn.commit()

    lines = [f"**📜 政策発表**: {ev.title}", f"<{ev.url or '(no url)'}>", "", "**仮説**:"]
    for h in hypotheses:
        lines.append(
            f"- `{h.metric_id}` {h.direction.value} (>{h.magnitude_threshold_pct}%) "
            f"in {h.horizon_months}mo via `{h.transmission_channel}`"
        )
    discord_post.post("policy", "\n".join(lines))

    # If this looks like a hard rate action from a central bank source, also
    # fire a BREAKING alert (Mode D). Rate decisions are the highest-impact
    # events in the calendar; the LLM should react immediately, not wait for
    # the next morning brief.
    text = f"{ev.title} {ev.body or ''}".lower()
    rate_action_keywords = (
        "basis point", "bps", "rate hike", "rate cut", "rate decision",
        "利上げ", "利下げ", "政策金利",
    )
    if any(kw in text for kw in rate_action_keywords):
        _post_breaking(
            conn,
            trigger_type="policy",
            category=f"policy_rate:{ev.source}",
            source_event_id=ev.id,
            summary=(
                f"{ev.source} が政策発表: '{ev.title}' "
                f"({ev.ts.isoformat()}) — 利上げ/利下げ相当のシグナル検知"
            ),
        )


def _detect_and_post_surprise(conn, metric: MetricDefinition) -> None:
    series = _metric_series(conn, metric.id)
    signal = surprise_mod.detect(metric, series)
    if signal is None:
        return

    # de-dup: skip if already posted for this metric_id + ts
    exists = conn.execute(
        "SELECT 1 FROM surprises WHERE metric_id = ? AND ts = ?",
        (signal.metric_id, signal.ts),
    ).fetchone()
    if exists:
        return

    try:
        interpretation = interpret.interpret_surprise(signal)
    except Exception as e:
        interpretation = f"(LLM interpretation unavailable: {e})"

    conn.execute(
        "INSERT INTO surprises (ts, metric_id, value, zscore, llm_interpretation) "
        "VALUES (?, ?, ?, ?, ?)",
        (signal.ts, signal.metric_id, signal.value, signal.zscore, interpretation),
    )
    conn.commit()

    msg = (
        f"**⚡ サプライズ: {metric.name}** (z={signal.zscore:+.2f})\n"
        f"値: {signal.value} {metric.unit}\n"
        f"時刻: {signal.ts.isoformat()}\n\n{interpretation}"
    )
    discord_post.post("surprise", msg)
    target = "markets" if metric.category in {"fx", "rate", "spread", "equity_index", "volatility"} else "macro_structural"
    discord_post.post(target, msg)

    # Extreme moves (>4σ, ~0.006% probability if Gaussian) additionally fire a
    # BREAKING analyst-voice note. Very rare, so cost is bounded.
    if abs(signal.zscore) >= 4.0:
        _post_breaking(
            conn,
            trigger_type="surprise",
            category=f"surprise:{metric.id}",
            summary=(
                f"{metric.name} ({metric.id}) が {signal.value} {metric.unit} "
                f"に到達、z-score {signal.zscore:+.2f} — >4σ の極端な動き "
                f"(発生時刻 {signal.ts.isoformat()})"
            ),
        )


def _post_breaking(
    conn,
    trigger_type: str,
    summary: str,
    category: str = "general",
    source_event_id: str | None = None,
) -> None:
    """Fire an immediate BREAKING alert (Mode D style) to the policy channel.

    Persists to breaking_alerts for the de-dup logic. Callers that need
    de-dup (geopolitical, where the same event may hit multiple sources)
    should check ``_recently_fired_breaking`` first.
    """
    now = datetime.now(timezone.utc)
    try:
        note = morning_note.generate_breaking(conn, trigger_type, summary)
    except Exception as e:
        _log_error(f"BREAKING generation failed: {e}")
        return
    conn.execute(
        "INSERT INTO breaking_alerts (ts, category, trigger_type, source_event_id, summary) "
        "VALUES (?, ?, ?, ?, ?)",
        (now, category, trigger_type, source_event_id, summary[:500]),
    )
    conn.commit()
    discord_post.post("policy", f"🚨 **BREAKING**\n\n{note}")


def _recently_fired_breaking(
    conn, category: str, within_hours: int = 24
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
    row = conn.execute(
        "SELECT 1 FROM breaking_alerts WHERE category = ? AND ts >= ? LIMIT 1",
        (category, cutoff),
    ).fetchone()
    return row is not None


def _check_geopolitical_breaking(conn, ev: IngestedEvent, combined_text: str) -> None:
    """Fire BREAKING if the event title/body matches a Tier 1 severity phrase.

    De-duped per (category, 24h) so a running Ukraine war news cycle doesn't
    fire 20 times per day; the first hit does.
    """
    category = breaking_classifier.classify(combined_text)
    if category is None:
        return
    if _recently_fired_breaking(conn, category, within_hours=24):
        return
    summary = (
        f"[{ev.source}] {ev.title} "
        f"(検出カテゴリ: {category}, 時刻 {ev.ts.isoformat()})"
    )
    _post_breaking(
        conn,
        trigger_type="geopolitical",
        summary=summary,
        category=category,
        source_event_id=ev.id,
    )


def _post_morning_briefing() -> None:
    """If any high-importance policy events are scheduled in the next 48h,
    post a heads-up to #policy so the operator (and the LLM's context on
    later interpretations) knows what to watch.
    """
    upcoming = policy_calendar.upcoming(within_hours=48)
    if not upcoming:
        return
    lines = ["**📅 今後 48h の政策イベント (高重要度)**", ""]
    now = datetime.now(timezone.utc)
    for e in upcoming:
        offset_h = (e.date - now).total_seconds() / 3600
        lines.append(
            f"- **{e.name}** — {offset_h:+.0f}h後 ({e.date.strftime('%Y-%m-%d %H:%M UTC')}, {e.entity.upper()})"
        )
    try:
        discord_post.post("policy", "\n".join(lines))
    except Exception as e:
        _log_error(f"morning briefing failed: {e}")


def _post_raw(ev: IngestedEvent) -> None:
    msg = f"[{ev.source}] **{ev.title}**\n<{ev.url or '(no url)'}>"
    try:
        discord_post.post("raw_feed", msg)
    except Exception as e:
        _log_error(f"raw post failed: {e}")


def _post_retrospective(policy_id: str, description: str, results) -> None:
    lines = [f"**🔍 事後検証**: {description}", ""]
    for r in results:
        lines.append(
            f"- `{r.hypothesis.metric_id}` {r.hypothesis.direction.value}: "
            f"**{r.verdict.value}** ({r.machine_note})"
        )
        if r.llm_reasoning:
            lines.append(f"  → {r.llm_reasoning.strip()}")
    discord_post.post("retrospective", "\n".join(lines))


def _verify(conn, hypothesis, announced_at: datetime):
    """Machine-judge a hypothesis at horizon end.

    Baseline = last value at or before announced_at.
    Observed = latest value in DB.
    """
    baseline_row = conn.execute(
        "SELECT ts, value FROM metrics WHERE metric_id = ? AND ts <= ? "
        "ORDER BY ts DESC LIMIT 1",
        (hypothesis.metric_id, announced_at),
    ).fetchone()
    latest_row = conn.execute(
        "SELECT ts, value FROM metrics WHERE metric_id = ? ORDER BY ts DESC LIMIT 1",
        (hypothesis.metric_id,),
    ).fetchone()
    if not baseline_row or not latest_row:
        return None
    return retrospective.judge(
        hypothesis,
        baseline_value=baseline_row["value"],
        observed_value=latest_row["value"],
        baseline_ts=baseline_row["ts"],
        observed_ts=latest_row["ts"],
    )


def _metric_last_ts(conn, metric_id: str) -> datetime | None:
    row = conn.execute(
        "SELECT MAX(ts) as ts FROM metrics WHERE metric_id = ?", (metric_id,)
    ).fetchone()
    return row["ts"] if row else None


def __hypothesis_from_dict(d: dict):
    from src.models import Hypothesis
    return Hypothesis(**d)


def _log_error(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


# ────────────────────── entry ──────────────────────


JOBS = {
    "ingest-frequent": job_ingest_frequent,
    "ingest-daily": job_ingest_daily,
    "ingest-weekly": job_ingest_weekly,
    "retrospective": job_retrospective,
    "daily-briefing": job_daily_briefing,
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in JOBS:
        print(f"Usage: python -m src.main <{ ' | '.join(JOBS) }>", file=sys.stderr)
        sys.exit(2)
    try:
        JOBS[sys.argv[1]]()
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
