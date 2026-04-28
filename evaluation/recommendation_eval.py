"""Recommendation evaluation helpers and CLI."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..data import get_db


@dataclass
class RecommendationJudgment:
    """One manually labeled relevance judgment for a feed item."""

    item_id: str
    relevant: bool
    pool_type: str | None = None
    feed_date: str | None = None


def load_judgments(path: str | Path) -> list[RecommendationJudgment]:
    """Load recommendation judgments from JSON or JSONL."""
    source = Path(path)
    raw = source.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if source.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        rows = json.loads(raw)
    return [RecommendationJudgment(**row) for row in rows]


def precision_at_k(items: list[bool], k: int) -> float:
    """Compute precision@k from a ranked boolean relevance list."""
    if k <= 0:
        raise ValueError("k must be positive")
    sliced = items[:k]
    if not sliced:
        return 0.0
    return round(sum(1 for item in sliced if item) / len(sliced), 3)


def evaluate_precision_at_k(
    *,
    db_path: str,
    judgments: list[RecommendationJudgment],
    feed_date: str | None = None,
    ks: tuple[int, ...] = (5, 10),
) -> dict[str, Any]:
    """Evaluate overall and per-pool precision using feed_history order."""
    feed_rows = _load_feed_rows(db_path=db_path, feed_date=feed_date)
    judgment_map = {entry.item_id: entry for entry in judgments}

    overall = [judgment_map[row["item_id"]].relevant for row in feed_rows if row["item_id"] in judgment_map]
    per_pool: dict[str, list[bool]] = {"precision": [], "exploration": []}
    for row in feed_rows:
        judgment = judgment_map.get(row["item_id"])
        if judgment is None:
            continue
        per_pool.setdefault(row["pool_type"], []).append(judgment.relevant)

    summary = {
        "feed_date": feed_date or (feed_rows[0]["feed_date"] if feed_rows else None),
        "judged_items": len(overall),
        "overall": {f"precision@{k}": precision_at_k(overall, k) for k in ks},
        "by_pool": {
            pool: {f"precision@{k}": precision_at_k(flags, k) for k in ks}
            for pool, flags in per_pool.items()
            if flags
        },
    }
    return summary


def _load_feed_rows(*, db_path: str, feed_date: str | None) -> list[Any]:
    """Load ranked feed rows from SQLite."""
    conn = get_db(db_path)
    try:
        if feed_date:
            rows = conn.execute(
                """
                SELECT feed_date, item_id, pool_type, final_score, novelty_score, source_platform
                FROM feed_history
                WHERE feed_date = ?
                ORDER BY id ASC
                """,
                (feed_date,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT feed_date, item_id, pool_type, final_score, novelty_score, source_platform
                FROM feed_history
                WHERE feed_date = (SELECT MAX(feed_date) FROM feed_history)
                ORDER BY id ASC
                """
            ).fetchall()
        return list(rows)
    finally:
        conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate recommendation precision@k from feed_history.")
    parser.add_argument("judgments", help="Path to a JSON or JSONL relevance-judgment file.")
    parser.add_argument("--db-path", required=True, help="SQLite database path.")
    parser.add_argument("--feed-date", help="Optional feed_date to evaluate. Defaults to latest date in SQLite.")
    parser.add_argument("--output", help="Optional output JSON report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = evaluate_precision_at_k(
        db_path=args.db_path,
        judgments=load_judgments(args.judgments),
        feed_date=args.feed_date,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
