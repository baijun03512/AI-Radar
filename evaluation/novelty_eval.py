"""Novelty Scorer evaluation utilities and CLI."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from ..agents.novelty_scorer import NoveltyAssessment, NoveltyDimensions, NoveltyScorerAgent
from ..schemas.contracts import CrawledItem

LABEL_NEW = "馃啎"
LABEL_KNOWN = "馃攣"
LABEL_WATCH = "馃搶"
LABEL_LOW = "鉂?"


@dataclass
class NoveltyGroundTruth:
    """One manually labeled novelty evaluation sample."""

    item_id: str
    title: str
    summary: str
    source_platform: str
    source_layer: str
    source_url: str = ""
    published_at: str = ""
    fetched_at: str = ""
    expected_label: str = LABEL_WATCH
    is_known: bool = False


@dataclass
class VariantMetrics:
    """Metrics for one novelty-scoring variant."""

    variant: str
    total: int
    correct: int
    accuracy: float


def load_ground_truth(path: str | Path) -> list[NoveltyGroundTruth]:
    """Load novelty ground-truth entries from JSON or JSONL."""
    source = Path(path)
    raw = source.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if source.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        rows = json.loads(raw)
    return [NoveltyGroundTruth(**row) for row in rows]


def evaluate_novelty_variants(entries: Iterable[NoveltyGroundTruth]) -> dict[str, Any]:
    """Compare baseline, temporal, and full novelty variants against ground truth."""
    scorer = NoveltyScorerAgent()
    materialized = list(entries)
    metrics: list[VariantMetrics] = []
    detailed: dict[str, list[dict[str, Any]]] = {}

    for variant in ("baseline", "temporal", "full"):
        rows: list[dict[str, Any]] = []
        correct = 0
        for entry in materialized:
            assessment = score_variant(scorer, entry, variant)
            matched = assessment.novelty_label == entry.expected_label
            if matched:
                correct += 1
            rows.append(
                {
                    "item_id": entry.item_id,
                    "title": entry.title,
                    "expected_label": entry.expected_label,
                    "predicted_label": assessment.novelty_label,
                    "novelty_score": assessment.novelty_score,
                    "is_correct": matched,
                }
            )
        total = len(materialized)
        metrics.append(
            VariantMetrics(
                variant=variant,
                total=total,
                correct=correct,
                accuracy=round(correct / total, 3) if total else 0.0,
            )
        )
        detailed[variant] = rows

    return {
        "summary": [asdict(metric) for metric in metrics],
        "details": detailed,
    }


def score_variant(
    scorer: NoveltyScorerAgent,
    entry: NoveltyGroundTruth,
    variant: str,
) -> NoveltyAssessment:
    """Score one entry with a specific evaluation variant."""
    item = CrawledItem(
        item_id=entry.item_id,
        title=entry.title,
        summary=entry.summary,
        source_platform=entry.source_platform,
        source_layer=entry.source_layer,
        source_url=entry.source_url,
        published_at=entry.published_at,
        fetched_at=entry.fetched_at,
    )
    if variant == "baseline":
        return _baseline_assessment(scorer, item)
    if variant == "temporal":
        return _temporal_assessment(scorer, item, known=entry.is_known)
    if variant == "full":
        known_ids = {entry.item_id} if entry.is_known else set()
        return scorer.assess_item(item, known_item_ids=known_ids)
    raise ValueError(f"Unknown novelty variant: {variant}")


def _baseline_assessment(scorer: NoveltyScorerAgent, item: CrawledItem) -> NoveltyAssessment:
    """Approximate an LLM-only baseline using text/product heuristics only."""
    evidence: list[str] = []
    dimensions = NoveltyDimensions(
        tech_novelty=0.5,
        product_novelty=scorer._product_novelty(item, evidence),
        maturity=scorer._maturity(item, evidence),
        market_signal=scorer._market_signal(item, evidence),
    )
    score = round(
        (
            dimensions.tech_novelty
            + dimensions.product_novelty
            + dimensions.maturity
            + dimensions.market_signal
        )
        / 4,
        3,
    )
    return NoveltyAssessment(
        item_id=item.item_id,
        novelty_label=scorer._label_for_score(score, False),
        novelty_score=score,
        dimensions=dimensions,
        evidence=evidence,
        reason="baseline text-only heuristic",
        is_verified=False,
    )


def _temporal_assessment(
    scorer: NoveltyScorerAgent,
    item: CrawledItem,
    *,
    known: bool,
) -> NoveltyAssessment:
    """Approximate the middle variant by adding time checks but skipping mutual verification."""
    evidence: list[str] = []
    dimensions = NoveltyDimensions(
        tech_novelty=scorer._tech_novelty(item, evidence),
        product_novelty=scorer._product_novelty(item, evidence),
        maturity=scorer._maturity(item, evidence),
        market_signal=scorer._market_signal(item, evidence),
    )
    if known:
        dimensions.product_novelty = min(dimensions.product_novelty, 0.25)
        dimensions.market_signal = min(dimensions.market_signal, 0.4)
        evidence.append("known item adjustment applied")
    score = round(
        (
            dimensions.tech_novelty
            + dimensions.product_novelty
            + dimensions.maturity
            + dimensions.market_signal
        )
        / 4,
        3,
    )
    return NoveltyAssessment(
        item_id=item.item_id,
        novelty_label=scorer._label_for_score(score, known),
        novelty_score=score,
        dimensions=dimensions,
        evidence=evidence,
        reason="temporal heuristic with known-item adjustment",
        is_verified=False,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate novelty-scoring variants against ground truth.")
    parser.add_argument("ground_truth", help="Path to a JSON or JSONL ground-truth file.")
    parser.add_argument("--output", help="Optional output JSON report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = evaluate_novelty_variants(load_ground_truth(args.ground_truth))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
