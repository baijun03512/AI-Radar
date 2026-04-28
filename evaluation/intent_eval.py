"""Intent-classification evaluation helpers and CLI."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..agents.chat_agent import ChatAgent
from ..runtime.tool_registry import ToolRegistry


@dataclass
class IntentGroundTruth:
    """One manually labeled query for intent evaluation."""

    query: str
    expected_intent: str


def load_ground_truth(path: str | Path) -> list[IntentGroundTruth]:
    """Load intent labels from JSON or JSONL."""
    source = Path(path)
    raw = source.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if source.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        rows = json.loads(raw)
    return [IntentGroundTruth(**row) for row in rows]


def evaluate_intent_classifier(entries: list[IntentGroundTruth]) -> dict[str, Any]:
    """Evaluate ChatAgent.detect_intent against a labeled query set."""
    agent = ChatAgent(ToolRegistry())
    labels = ("exploratory", "deep_dive", "comparison")
    confusion = {label: {other: 0 for other in labels} for label in labels}
    details: list[dict[str, Any]] = []
    correct = 0

    for entry in entries:
        predicted = agent.detect_intent(entry.query)
        confusion[entry.expected_intent][predicted] += 1
        is_correct = predicted == entry.expected_intent
        if is_correct:
            correct += 1
        details.append(
            {
                "query": entry.query,
                "expected_intent": entry.expected_intent,
                "predicted_intent": predicted,
                "is_correct": is_correct,
            }
        )

    total = len(entries)
    return {
        "summary": {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total, 3) if total else 0.0,
        },
        "confusion_matrix": confusion,
        "details": details,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate chat intent classification against labeled queries.")
    parser.add_argument("ground_truth", help="Path to a JSON or JSONL intent ground-truth file.")
    parser.add_argument("--output", help="Optional output JSON report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = evaluate_intent_classifier(load_ground_truth(args.ground_truth))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

