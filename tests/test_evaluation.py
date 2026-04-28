"""Phase-7 evaluation-script tests."""
from __future__ import annotations

from pathlib import Path

from ai_radar.data import get_db, init_db
from ai_radar.evaluation.novelty_eval import (
    LABEL_NEW,
    LABEL_WATCH,
    NoveltyGroundTruth,
    evaluate_novelty_variants,
)
from ai_radar.evaluation.intent_eval import IntentGroundTruth, evaluate_intent_classifier
from ai_radar.evaluation.recommendation_eval import (
    RecommendationJudgment,
    evaluate_precision_at_k,
    precision_at_k,
)
from ai_radar.evaluation.wiki_quality_eval import WikiQualitySample, evaluate_wiki_quality


def test_novelty_eval_compares_three_variants() -> None:
    """Novelty evaluation should return summary rows for all three variants."""
    entries = [
        NoveltyGroundTruth(
            item_id="n1",
            title="New AI benchmark for runtime agents",
            summary="Introducing a new benchmark for agent workflows in production",
            source_platform="arxiv",
            source_layer="瀛︽湳灞?",
            published_at="2026-04-20T00:00:00+00:00",
            fetched_at="2026-04-28T00:00:00+00:00",
            expected_label=LABEL_NEW,
        ),
        NoveltyGroundTruth(
            item_id="n2",
            title="Workflow automation discussion",
            summary="Real user feedback on ongoing workflow automation efforts",
            source_platform="reddit",
            source_layer="绀惧尯灞?",
            published_at="2026-03-01T00:00:00+00:00",
            fetched_at="2026-04-28T00:00:00+00:00",
            expected_label=LABEL_WATCH,
        ),
    ]

    report = evaluate_novelty_variants(entries)

    variants = {row["variant"] for row in report["summary"]}
    assert variants == {"baseline", "temporal", "full"}
    assert len(report["details"]["full"]) == 2


def test_precision_at_k_helper() -> None:
    """Precision@k should use the top-k slice only."""
    assert precision_at_k([True, False, True, True], 2) == 0.5
    assert precision_at_k([True, False, True, True], 3) == 0.667


def test_recommendation_eval_reads_feed_history(tmp_path: Path) -> None:
    """Recommendation evaluation should compute overall and per-pool precision from SQLite."""
    db_path = tmp_path / "radar.db"
    init_db(db_path)
    conn = get_db(db_path)
    try:
        conn.execute(
            """
            INSERT INTO feed_history (
                feed_date, item_id, pool_type, final_score, novelty_score,
                preference_score, novelty_label, source_platform, source_layer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-04-28", "p1", "precision", 0.91, 0.8, 0.9, LABEL_NEW, "product_hunt", "industry"),
        )
        conn.execute(
            """
            INSERT INTO feed_history (
                feed_date, item_id, pool_type, final_score, novelty_score,
                preference_score, novelty_label, source_platform, source_layer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-04-28", "e1", "exploration", 0.61, 0.61, 0.0, LABEL_WATCH, "reddit", "community"),
        )
        conn.commit()
    finally:
        conn.close()

    report = evaluate_precision_at_k(
        db_path=str(db_path),
        feed_date="2026-04-28",
        judgments=[
            RecommendationJudgment(item_id="p1", relevant=True),
            RecommendationJudgment(item_id="e1", relevant=False),
        ],
    )

    assert report["overall"]["precision@5"] == 0.5
    assert report["by_pool"]["precision"]["precision@5"] == 1.0
    assert report["by_pool"]["exploration"]["precision@5"] == 0.0


def test_intent_eval_reports_accuracy_and_confusion_matrix() -> None:
    """Intent evaluation should surface aggregate accuracy and confusion details."""
    report = evaluate_intent_classifier(
        [
            IntentGroundTruth(query="What is this product?", expected_intent="exploratory"),
            IntentGroundTruth(query="How does it work under the hood?", expected_intent="deep_dive"),
            IntentGroundTruth(query="Compare MCP vs Agents SDK", expected_intent="comparison"),
        ]
    )

    assert report["summary"]["accuracy"] == 1.0
    assert report["confusion_matrix"]["comparison"]["comparison"] == 1


def test_wiki_quality_eval_scores_dimension_summary() -> None:
    """Wiki quality evaluation should return both per-page and average scores."""
    report = evaluate_wiki_quality(
        [
            WikiQualitySample(
                name="MCP",
                one_liner="Protocol layer for tool and server interoperability.",
                tags=["industry", "tooling"],
                source_layer="industry",
                tech_principle="MCP standardizes how agent clients and external tools exchange structured calls.",
                product_impl="It improves integration portability across products and runtimes.",
                user_feedback="Teams use it to reduce custom connector maintenance.",
                chat_notes="Useful when comparing plugin layers and tool abstraction boundaries.",
                expected_min_score=3.0,
            )
        ]
    )

    assert report["summary"]["count"] == 1
    assert report["details"][0]["meets_expectation"] is True
    assert report["summary"]["average_scores"]["overall"] >= 3.0
