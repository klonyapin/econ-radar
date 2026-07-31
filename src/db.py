from __future__ import annotations

import sqlite3
from pathlib import Path

STATE_DB_PATH = Path(__file__).resolve().parent.parent / "state" / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    metric_id TEXT NOT NULL,
    ts TIMESTAMP NOT NULL,
    value REAL,
    source TEXT,
    PRIMARY KEY (metric_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    ts TIMESTAMP NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    title TEXT NOT NULL,
    body TEXT,
    entities TEXT,
    sentiment REAL,
    posted_to_discord INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);

CREATE TABLE IF NOT EXISTS surprises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL,
    metric_id TEXT NOT NULL,
    value REAL NOT NULL,
    zscore REAL NOT NULL,
    llm_interpretation TEXT,
    posted_to_discord INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_surprises_ts ON surprises(ts);

CREATE TABLE IF NOT EXISTS policy_events (
    id TEXT PRIMARY KEY,
    announced_at TIMESTAMP NOT NULL,
    description TEXT NOT NULL,
    source_event_id TEXT,
    hypotheses TEXT NOT NULL,
    verified_at TIMESTAMP,
    verification_result TEXT,
    posted_to_discord INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_policy_events_announced ON policy_events(announced_at);

CREATE TABLE IF NOT EXISTS job_runs (
    job_name TEXT PRIMARY KEY,
    last_success_ts TIMESTAMP,
    last_processed_cursor TEXT
);
"""


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or STATE_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    initialize()
    print(f"Initialized DB at {STATE_DB_PATH}")
