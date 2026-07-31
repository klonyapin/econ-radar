from __future__ import annotations

import ast
import sqlite3
from datetime import datetime

import pandas as pd

from src.models import MetricDefinition

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)


def refresh(conn: sqlite3.Connection, metric: MetricDefinition) -> int:
    """Recompute a derived metric from its components and upsert values.

    Aligns components on the union of dates using forward-fill so a daily
    series (e.g., US_10Y) can combine with a monthly one (e.g., JP_10Y).
    Returns the number of rows written.
    """
    if not metric.derived_from or not metric.formula:
        return 0

    frames: dict[str, pd.Series] = {}
    for cid in metric.derived_from:
        rows = conn.execute(
            "SELECT ts, value FROM metrics WHERE metric_id = ? ORDER BY ts", (cid,)
        ).fetchall()
        if not rows:
            return 0
        s = pd.Series(
            data=[r["value"] for r in rows],
            index=pd.to_datetime([r["ts"] for r in rows]),
            name=cid,
        )
        frames[cid] = s

    combined = pd.DataFrame(frames).sort_index().ffill().dropna()
    if combined.empty:
        return 0

    result = _eval_formula(metric.formula, combined)

    n = 0
    for ts, val in result.items():
        if pd.isna(val):
            continue
        conn.execute(
            "INSERT INTO metrics (metric_id, ts, value, source) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(metric_id, ts) DO UPDATE SET value = excluded.value",
            (metric.id, ts.to_pydatetime(), float(val), "derived"),
        )
        n += 1
    conn.commit()
    return n


def _eval_formula(expr: str, df: pd.DataFrame) -> pd.Series:
    tree = ast.parse(expr, mode="eval")
    return _walk(tree.body, df)


def _walk(node: ast.AST, df: pd.DataFrame):
    if isinstance(node, ast.Name):
        if node.id not in df.columns:
            raise ValueError(f"Formula references unknown component metric: {node.id}")
        return df[node.id]
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ValueError(f"Formula op not allowed: {type(node.op).__name__}")
        left = _walk(node.left, df)
        right = _walk(node.right, df)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        return left / right
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_walk(node.operand, df)
    raise ValueError(f"Formula node not allowed: {ast.dump(node)}")
