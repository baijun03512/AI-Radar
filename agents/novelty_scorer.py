"""Heuristic novelty scoring with evidence and lightweight verification."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..schemas.contracts import CrawledItem, ScoredItem


@dataclass
class NoveltyDimensions:
    """Four scoring dimensions from the PRD."""

    tech_novelty: float
    product_novelty: float
    maturity: float
    market_signal: float


@dataclass
class NoveltyAssessment:
    """Rich novelty assessment with scoring evidence."""

    item_id: str
    novelty_label: str
    novelty_score: float
    dimensions: NoveltyDimensions
    evidence: list[str] = field(default_factory=list)
    reason: str = ""
    is_verified: bool = False


class NoveltyScorerAgent:
    """Score crawled items for novelty using deterministic heuristics."""

    SOURCE_BASELINES = {
        "学术层": 0.75,
        "工业层": 0.65,
        "社区层": 0.55,
    }

    SOURCE_LAYER_ICONS = {
        "学术层": "📚",
        "工业层": "🏭",
        "社区层": "💬",
    }

    def assess_item(
        self,
        item: CrawledItem,
        *,
        known_item_ids: set[str] | None = None,
        secondary_verify: bool = True,
    ) -> NoveltyAssessment:
        """Produce a novelty assessment for one crawled item."""
        known = known_item_ids or set()
        evidence: list[str] = []
        dimensions = NoveltyDimensions(
            tech_novelty=self._tech_novelty(item, evidence),
            product_novelty=self._product_novelty(item, evidence),
            maturity=self._maturity(item, evidence),
            market_signal=self._market_signal(item, evidence),
        )

        if item.item_id in known:
            dimensions.product_novelty = min(dimensions.product_novelty, 0.25)
            dimensions.market_signal = min(dimensions.market_signal, 0.4)
            evidence.append("knowledge base: item_id already seen before")

        novelty_score = round(
            (
                dimensions.tech_novelty
                + dimensions.product_novelty
                + dimensions.maturity
                + dimensions.market_signal
            )
            / 4,
            3,
        )
        label = self._label_for_score(novelty_score, item.item_id in known)
        verified = secondary_verify and self._secondary_verification(novelty_score, dimensions)
        reason = self._reason_from_dimensions(dimensions, item.source_layer)
        return NoveltyAssessment(
            item_id=item.item_id,
            novelty_label=label,
            novelty_score=novelty_score,
            dimensions=dimensions,
            evidence=evidence,
            reason=reason,
            is_verified=verified,
        )

    def score_batch(
        self,
        items: list[CrawledItem],
        *,
        known_item_ids: set[str] | None = None,
    ) -> list[ScoredItem]:
        """Score all crawled items and emit recommender-facing contracts."""
        known = known_item_ids or set()
        scored: list[ScoredItem] = []
        for item in items:
            assessment = self.assess_item(item, known_item_ids=known)
            pool = item.pool
            scored.append(
                ScoredItem(
                    item_id=item.item_id,
                    title=item.title,
                    summary=item.summary,
                    source_platform=item.source_platform,
                    source_layer=item.source_layer,
                    source_url=item.source_url,
                    novelty_score=assessment.novelty_score,
                    novelty_label=assessment.novelty_label,
                    novelty_reason=f"{assessment.reason} | evidence: {'; '.join(assessment.evidence[:3])}",
                    is_verified=assessment.is_verified,
                    pool=pool,
                )
            )
        return scored

    def _tech_novelty(self, item: CrawledItem, evidence: list[str]) -> float:
        """Estimate technical novelty from recency and source layer."""
        score = self.SOURCE_BASELINES.get(item.source_layer, 0.5)
        published = self._parse_datetime(item.published_at)
        if published is not None:
            delta = datetime.now(timezone.utc) - published
            if delta <= timedelta(days=30):
                score += 0.2
                evidence.append("published within 30 days")
            elif delta <= timedelta(days=90):
                score += 0.1
                evidence.append("published within 90 days")
            else:
                score -= 0.15
                evidence.append("older than 90 days")
        if "agent" in item.title.lower() or "agent" in item.summary.lower():
            score += 0.05
            evidence.append("agent-related keyword present")
        return self._clamp(score)

    def _product_novelty(self, item: CrawledItem, evidence: list[str]) -> float:
        """Estimate product novelty from textual cues."""
        score = 0.45 if item.source_layer == "学术层" else 0.55
        text = f"{item.title} {item.summary}".lower()
        for token in ("new", "launch", "release", "introducing", "open source", "benchmark"):
            if token in text:
                score += 0.08
                evidence.append(f"text cue: {token}")
                break
        return self._clamp(score)

    def _maturity(self, item: CrawledItem, evidence: list[str]) -> float:
        """Estimate implementation maturity from source type."""
        if item.source_layer == "工业层":
            evidence.append("industrial source suggests product readiness")
            return 0.8
        if item.source_layer == "社区层":
            evidence.append("community source suggests real-user discussion")
            return 0.6
        evidence.append("academic source suggests earlier-stage concept")
        return 0.45

    def _market_signal(self, item: CrawledItem, evidence: list[str]) -> float:
        """Estimate market signal from available metadata."""
        score = 0.5 if item.source_layer == "社区层" else 0.45
        text = (item.summary or "").lower()
        if any(token in text for token in ("users", "teams", "production", "feedback", "upvote")):
            score += 0.2
            evidence.append("market-signal keywords present")
        if item.source_layer == "工业层":
            score += 0.15
        return self._clamp(score)

    def _secondary_verification(self, score: float, dimensions: NoveltyDimensions) -> bool:
        """Simple mutual-check style verification for high-scoring items."""
        if score <= 0.7:
            return False
        spread = max(
            dimensions.tech_novelty,
            dimensions.product_novelty,
            dimensions.maturity,
            dimensions.market_signal,
        ) - min(
            dimensions.tech_novelty,
            dimensions.product_novelty,
            dimensions.maturity,
            dimensions.market_signal,
        )
        return spread <= 0.35

    def _label_for_score(self, score: float, known: bool) -> str:
        """Map a novelty score to the user-facing novelty label."""
        if known:
            return "🔁"
        if score >= 0.72:
            return "🆕"
        if score >= 0.58:
            return "📌"
        return "❓"

    def _reason_from_dimensions(self, dimensions: NoveltyDimensions, source_layer: str) -> str:
        """Create a compact reason string from the dimension balance."""
        parts = []
        if dimensions.tech_novelty >= 0.7:
            parts.append("high technical novelty")
        if dimensions.product_novelty >= 0.7:
            parts.append("fresh product angle")
        if dimensions.market_signal >= 0.65:
            parts.append("visible market discussion")
        if not parts:
            parts.append("moderate incremental update")
        return f"{source_layer}: " + ", ".join(parts)

    def _parse_datetime(self, value: str) -> datetime | None:
        """Best-effort ISO8601 datetime parsing."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _clamp(self, value: float) -> float:
        """Clamp one score to the 0-1 interval."""
        return round(max(0.0, min(1.0, value)), 3)
