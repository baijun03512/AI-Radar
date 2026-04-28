"""Phase-4 tests for novelty scoring and recommendation."""
from __future__ import annotations

from pathlib import Path

from ai_radar.agents import NoveltyScorerAgent, RecommenderAgent
from ai_radar.data import get_db, init_db
from ai_radar.schemas.contracts import CrawledItem


def sample_items() -> list[CrawledItem]:
    """Return three representative crawled items."""
    return [
        CrawledItem(
            item_id="a1",
            title="New AI agent benchmark",
            summary="Introducing a new benchmark for agent workflows with user feedback",
            source_platform="arxiv",
            source_layer="学术层",
            source_url="https://arxiv.test/a1",
            published_at="2026-04-20T00:00:00+00:00",
            fetched_at="2026-04-27T00:00:00+00:00",
        ),
        CrawledItem(
            item_id="p1",
            title="Launch AI coding assistant",
            summary="New release for developer teams in production",
            source_platform="product_hunt",
            source_layer="工业层",
            source_url="https://ph.test/p1",
            published_at="2026-04-25T00:00:00+00:00",
            fetched_at="2026-04-27T00:00:00+00:00",
        ),
        CrawledItem(
            item_id="r1",
            title="Thread on agent workflows",
            summary="Real user feedback on AI workflow automation",
            source_platform="reddit",
            source_layer="社区层",
            source_url="https://reddit.test/r1",
            published_at="2026-04-24T00:00:00+00:00",
            fetched_at="2026-04-27T00:00:00+00:00",
        ),
    ]


def test_novelty_scorer_emits_scored_items() -> None:
    """Batch scoring produces recommender-ready items with evidence-backed reasons."""
    scorer = NoveltyScorerAgent()
    scored = scorer.score_batch(sample_items())

    assert len(scored) == 3
    assert all(item.novelty_score > 0 for item in scored)
    assert any(item.novelty_label == "🆕" for item in scored)
    assert all("evidence:" in item.novelty_reason for item in scored)


def test_novelty_scorer_marks_known_items_as_incremental() -> None:
    """Known items should be downgraded toward the incremental label."""
    scorer = NoveltyScorerAgent()
    assessment = scorer.assess_item(sample_items()[0], known_item_ids={"a1"})
    assert assessment.novelty_label == "🔁"


def test_recommender_builds_dual_pool_feed_and_persists_history(tmp_path: Path) -> None:
    """Recommender splits precision/exploration pools and writes feed_history."""
    db_path = tmp_path / "radar.db"
    init_db(db_path)
    scorer = NoveltyScorerAgent()
    scored = scorer.score_batch(sample_items())
    recommender = RecommenderAgent(db_path=str(db_path))

    result = recommender.build_feed(
        scored,
        preferences={
            "interests": ["coding assistant", "agent workflows"],
            "exploration_ratio": 0.3,
            "feed_size": 6,
        },
    )

    assert result.feed.feed_date
    assert len(result.feed.precision_pool) >= 1
    assert len(result.feed.exploration_pool) >= 1

    conn = get_db(db_path)
    rows = conn.execute("SELECT pool_type, COUNT(*) AS n FROM feed_history GROUP BY pool_type").fetchall()
    conn.close()
    summary = {row["pool_type"]: row["n"] for row in rows}
    assert "precision" in summary
    assert "exploration" in summary


def test_recommender_detects_filter_bubble_pattern(tmp_path: Path) -> None:
    """Five straight days of skipping exploration should trigger a warning."""
    db_path = tmp_path / "radar.db"
    init_db(db_path)
    conn = get_db(db_path)
    try:
        for day in range(5):
            conn.execute(
                """
                INSERT INTO user_actions (item_id, item_title, action, pool_type, novelty_label, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now', ?))
                """,
                (f"id-{day}", "demo", "skip_temp", "exploration", "❓", f"-{day} day"),
            )
        conn.commit()
    finally:
        conn.close()

    recommender = RecommenderAgent(db_path=str(db_path))
    warning = recommender.build_feed(
        NoveltyScorerAgent().score_batch(sample_items()),
        preferences={"interests": ["agent workflows"]},
    ).filter_bubble_warning
    assert warning
