"""Wiki-quality evaluation helpers and CLI."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..schemas.contracts import WikiPage


@dataclass
class WikiQualitySample:
    """One wiki page sample used for quality evaluation."""

    name: str
    one_liner: str = ""
    tags: list[str] | None = None
    source_layer: str = "community"
    tech_principle: str = ""
    product_impl: str = ""
    user_feedback: str = ""
    chat_notes: str = ""
    expected_min_score: float | None = None


def load_samples(path: str | Path) -> list[WikiQualitySample]:
    """Load wiki evaluation samples from JSON or JSONL."""
    source = Path(path)
    raw = source.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if source.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        rows = json.loads(raw)
    return [WikiQualitySample(**row) for row in rows]


def evaluate_wiki_quality(samples: list[WikiQualitySample]) -> dict[str, Any]:
    """Evaluate wiki-page quality with a deterministic four-dimension rubric."""
    details: list[dict[str, Any]] = []
    totals = {
        "completeness": 0.0,
        "traceability": 0.0,
        "technical_clarity": 0.0,
        "reuse_value": 0.0,
        "overall": 0.0,
    }

    for sample in samples:
        page = WikiPage(
            name=sample.name,
            one_liner=sample.one_liner,
            tags=sample.tags or [],
            source_layer=sample.source_layer,
            tech_principle=sample.tech_principle,
            product_impl=sample.product_impl,
            user_feedback=sample.user_feedback,
            chat_notes=sample.chat_notes,
        )
        dimensions = _score_dimensions(page)
        overall = round(sum(dimensions.values()) / len(dimensions), 2)
        row = {
            "name": sample.name,
            "dimensions": dimensions,
            "overall": overall,
        }
        if sample.expected_min_score is not None:
            row["meets_expectation"] = overall >= sample.expected_min_score
            row["expected_min_score"] = sample.expected_min_score
        details.append(row)
        for key, value in dimensions.items():
            totals[key] += value
        totals["overall"] += overall

    count = len(samples) or 1
    averages = {key: round(value / count, 2) for key, value in totals.items()}
    return {
        "summary": {
            "count": len(samples),
            "average_scores": averages,
        },
        "details": details,
    }


def _score_dimensions(page: WikiPage) -> dict[str, float]:
    """Score a wiki page on the PRD-aligned quality rubric."""
    completeness = 1.0
    if page.one_liner:
        completeness += 1.0
    if page.tech_principle:
        completeness += 1.0
    if page.product_impl:
        completeness += 1.0
    if page.user_feedback:
        completeness += 1.0

    traceability = 1.0
    if page.tags:
        traceability += 1.5
    if page.source_layer:
        traceability += 1.0
    if page.chat_notes:
        traceability += 1.5

    technical_clarity = 1.0
    if len(page.tech_principle.strip()) >= 40:
        technical_clarity += 2.0
    elif page.tech_principle.strip():
        technical_clarity += 1.0
    if len(page.product_impl.strip()) >= 40:
        technical_clarity += 1.0
    if len(page.user_feedback.strip()) >= 20:
        technical_clarity += 1.0

    reuse_value = 1.0
    if page.one_liner:
        reuse_value += 1.0
    if page.tags:
        reuse_value += 1.0
    if page.chat_notes and len(page.chat_notes.strip()) >= 80:
        reuse_value += 1.0
    if page.tech_principle and page.product_impl:
        reuse_value += 1.0

    return {
        "completeness": round(min(completeness, 5.0), 2),
        "traceability": round(min(traceability, 5.0), 2),
        "technical_clarity": round(min(technical_clarity, 5.0), 2),
        "reuse_value": round(min(reuse_value, 5.0), 2),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate wiki page quality from JSON samples.")
    parser.add_argument("samples", help="Path to a JSON or JSONL wiki sample file.")
    parser.add_argument("--output", help="Optional output JSON report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = evaluate_wiki_quality(load_samples(args.samples))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
