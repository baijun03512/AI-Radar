"""Daily planning logic for the radar workflow."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from ..data import get_db, init_db


@dataclass
class CrawlTask:
    """One crawler task emitted by the orchestrator."""

    platform: str
    source_layer: str
    pool: str
    query: str
    max_results: int
    tool_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DailyPlan:
    """A daily crawl plan split into precision and exploration tasks."""

    plan_date: str
    tasks: list[CrawlTask]
    preferences_summary: dict[str, Any] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)


class OrchestratorAgent:
    """Generate the daily crawler plan from preferences and recent behavior."""

    PLATFORM_LAYERS = {
        "arxiv": "学术层",
        "product_hunt": "工业层",
        "reddit": "社区层",
    }

    DEFAULT_INTERESTS = ["AI agents", "developer tools", "LLM applications"]
    DEFAULT_EXPLORATION_QUERIES = ["open source AI", "multimodal AI", "AI workflow automation"]

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path
        init_db(db_path)

    def load_recent_actions(self, days: int = 3) -> list[sqlite3.Row]:
        """Load recent user behavior rows from SQLite."""
        conn = get_db(self.db_path)
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute(
                """
                SELECT item_id, item_title, action, pool_type, novelty_label, chat_turns, created_at
                FROM user_actions
                WHERE created_at >= ?
                ORDER BY created_at DESC
                """,
                (cutoff,),
            ).fetchall()
            return rows
        finally:
            conn.close()

    def build_daily_plan(
        self,
        preferences: dict[str, Any] | None = None,
        *,
        recent_actions: list[sqlite3.Row] | None = None,
    ) -> DailyPlan:
        """Build one day's crawl plan with precision and exploration tasks."""
        pref = preferences or {}
        actions = recent_actions if recent_actions is not None else self.load_recent_actions()
        interests = list(pref.get("interests") or self.DEFAULT_INTERESTS)
        preferred_platforms = list(
            pref.get("preferred_platforms") or ["product_hunt", "reddit", "arxiv"]
        )
        boosted_topics = self._normalize_topics(pref.get("boosted_topics"))
        suppressed_topics = set(self._normalize_topics(pref.get("suppressed_topics")))
        exploration_ratio = float(pref.get("exploration_ratio", 0.3))
        exploration_ratio = min(max(exploration_ratio, 0.1), 0.5)

        precision_topics = self._build_precision_topics(interests, boosted_topics, suppressed_topics)
        exploration_topics = self._build_exploration_topics(pref, boosted_topics, suppressed_topics)

        skip_count = sum(1 for row in actions if row["action"].startswith("skip"))
        open_count = sum(1 for row in actions if row["action"] == "open")
        save_count = sum(1 for row in actions if row["action"] == "save")
        rationale = [
            f"interests={', '.join(interests[:3])}",
            f"behavior=open:{open_count}, save:{save_count}, skip:{skip_count}",
            f"boosted_topics={', '.join(boosted_topics[:4]) or 'none'}",
            f"suppressed_topics={', '.join(sorted(suppressed_topics)[:4]) or 'none'}",
            f"exploration_ratio={exploration_ratio:.2f}",
        ]

        precision_results = max(1, round((1.0 - exploration_ratio) * 10 / max(len(preferred_platforms), 1)))
        exploration_results = max(1, round(exploration_ratio * 10 / 3))

        tasks: list[CrawlTask] = []
        for idx, platform in enumerate(preferred_platforms):
            query = precision_topics[idx % len(precision_topics)]
            tasks.append(
                CrawlTask(
                    platform=platform,
                    source_layer=self.PLATFORM_LAYERS.get(platform, "社区层"),
                    pool="precision",
                    query=query,
                    max_results=precision_results,
                    metadata={
                        "reason": "preferred interest coverage",
                        "boosted_match": any(token.lower() in query.lower() for token in boosted_topics),
                    },
                )
            )

        for idx, platform in enumerate(["arxiv", "product_hunt", "reddit"]):
            query = exploration_topics[idx % len(exploration_topics)]
            tasks.append(
                CrawlTask(
                    platform=platform,
                    source_layer=self.PLATFORM_LAYERS[platform],
                    pool="exploration",
                    query=query,
                    max_results=exploration_results,
                    metadata={
                        "reason": "exploration pool diversification",
                        "suppressed_filtered": any(
                            token.lower() in " ".join(pref.get("exploration_queries") or []).lower()
                            for token in suppressed_topics
                        ),
                    },
                )
            )

        return DailyPlan(
            plan_date=date.today().isoformat(),
            tasks=tasks,
            preferences_summary={
                "interests": interests,
                "preferred_platforms": preferred_platforms,
                "exploration_ratio": exploration_ratio,
                "boosted_topics": boosted_topics,
                "suppressed_topics": sorted(suppressed_topics),
            },
            rationale=rationale,
        )

    def _build_precision_topics(
        self,
        interests: list[str],
        boosted_topics: list[str],
        suppressed_topics: set[str],
    ) -> list[str]:
        """Blend explicit interests with lightweight boosted topics."""
        ordered: list[str] = []
        for topic in [*boosted_topics, *interests]:
            normalized = topic.strip()
            if not normalized:
                continue
            topic_tokens = {token.lower() for token in normalized.replace("-", " ").split()}
            if topic_tokens and topic_tokens.issubset(suppressed_topics):
                continue
            if normalized not in ordered:
                ordered.append(normalized)
        return ordered or list(self.DEFAULT_INTERESTS)

    def _build_exploration_topics(
        self,
        preferences: dict[str, Any],
        boosted_topics: list[str],
        suppressed_topics: set[str],
    ) -> list[str]:
        """Build exploration queries while down-weighting suppressed topics."""
        base_queries = list(preferences.get("exploration_queries") or self.DEFAULT_EXPLORATION_QUERIES)
        filtered = [query for query in base_queries if not self._contains_suppressed_topic(query, suppressed_topics)]
        if len(filtered) < 3:
            for topic in boosted_topics:
                candidate = f"{topic} open source"
                if candidate not in filtered and not self._contains_suppressed_topic(candidate, suppressed_topics):
                    filtered.append(candidate)
                if len(filtered) >= 3:
                    break
        return filtered or list(self.DEFAULT_EXPLORATION_QUERIES)

    @staticmethod
    def _normalize_topics(values: Any) -> list[str]:
        """Normalize lightweight topic preferences into a deduplicated list."""
        if not isinstance(values, list):
            return []
        normalized: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @staticmethod
    def _contains_suppressed_topic(query: str, suppressed_topics: set[str]) -> bool:
        """Return True when a query is dominated by a suppressed topic token."""
        lowered = query.lower()
        return any(topic in lowered for topic in suppressed_topics)
