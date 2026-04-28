"""Daily planning logic for the radar workflow.

OrchestratorAgent has two planning modes:
- LLM mode (when llm_client is supplied): reads preferences + recent behavior,
  asks the LLM to produce a structured JSON crawl plan, then converts it to
  CrawlTask objects.
- Rule mode (always available as fallback): deterministic keyword-based planning.

Any failure in LLM mode is caught and the rule-based plan is used instead,
so the agent is always stable regardless of API availability.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from ..data import get_db, init_db

logger = logging.getLogger(__name__)

_ORCHESTRATOR_SYSTEM_PROMPT = """\
You are the planning agent of an AI product radar system.

Given the user's preference profile and a summary of their recent interactions,
generate today's crawl plan.

Produce exactly 6 tasks in a JSON array:
- 3 tasks with "pool": "precision"  → targeted at the user's stated interests
- 3 tasks with "pool": "exploration" → diverse topics outside the comfort zone

Each task must follow this schema:
{
  "platform": "arxiv" | "product_hunt" | "reddit",
  "pool": "precision" | "exploration",
  "query": "<English search query, specific and actionable>",
  "reason": "<one Chinese sentence explaining why this query fits today's plan>"
}

Constraints:
- Use each platform at most twice across the 6 tasks.
- Precision queries must relate to boosted_topics or interests; avoid suppressed_topics.
- Exploration queries must introduce genuine diversity; avoid topics the user always skips.
- Respond ONLY with a valid JSON array, no markdown fences, no commentary.
"""


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
    """Generate the daily crawler plan from preferences and recent behavior.

    Args:
        db_path: Path to the SQLite database.  Defaults to the project default.
        llm_client: Optional LLMClient.  When provided the agent uses the LLM
            to generate the crawl plan; otherwise deterministic rule-based
            planning is used.
    """

    PLATFORM_LAYERS = {
        "arxiv": "学术层",
        "product_hunt": "工业层",
        "reddit": "社区层",
    }

    PLATFORM_MAX_RESULTS = {
        "arxiv": 3,
        "product_hunt": 3,
        "reddit": 3,
    }

    DEFAULT_INTERESTS = ["AI agents", "developer tools", "LLM applications"]
    DEFAULT_EXPLORATION_QUERIES = ["open source AI", "multimodal AI", "AI workflow automation"]

    def __init__(
        self,
        db_path: str | None = None,
        llm_client: Optional[Any] = None,
    ) -> None:
        self.db_path = db_path
        self._llm = llm_client
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
        """Build one day's crawl plan.

        Tries LLM-based planning first when a client is available.  Falls back
        to deterministic rule-based planning on any failure.
        """
        pref = preferences or {}
        actions = recent_actions if recent_actions is not None else self.load_recent_actions()

        if self._llm is not None:
            try:
                return self._llm_build_daily_plan(pref, actions)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "OrchestratorAgent LLM planning failed, using rule-based fallback: %s", exc
                )

        return self._rule_build_daily_plan(pref, actions)

    # ------------------------------------------------------------------
    # LLM planning
    # ------------------------------------------------------------------

    def _llm_build_daily_plan(
        self,
        preferences: dict[str, Any],
        recent_actions: list[sqlite3.Row],
    ) -> DailyPlan:
        """Ask the LLM to generate today's crawl plan as a structured JSON array."""
        action_summary = self._summarise_actions(recent_actions)
        pref_snapshot = {
            "interests": preferences.get("interests", self.DEFAULT_INTERESTS),
            "boosted_topics": preferences.get("boosted_topics", []),
            "suppressed_topics": preferences.get("suppressed_topics", []),
            "preferred_platforms": preferences.get(
                "preferred_platforms", ["product_hunt", "reddit", "arxiv"]
            ),
            "exploration_ratio": preferences.get("exploration_ratio", 0.3),
            "exploration_queries": preferences.get("exploration_queries", []),
        }

        user_msg = (
            f"Today's date: {date.today().isoformat()}\n\n"
            f"User preferences:\n{json.dumps(pref_snapshot, ensure_ascii=False, indent=2)}\n\n"
            f"Recent behavior summary (last 3 days):\n{action_summary}\n\n"
            "Generate today's crawl plan as a JSON array."
        )

        response = self._llm.call(
            messages=[{"role": "user", "content": user_msg}],
            system=_ORCHESTRATOR_SYSTEM_PROMPT,
            max_tokens=512,
        )

        tasks = self._parse_llm_plan(response.text, preferences)
        if not tasks:
            raise ValueError("LLM returned an empty or invalid task list")

        logger.debug("OrchestratorAgent LLM plan: %d tasks generated", len(tasks))

        return DailyPlan(
            plan_date=date.today().isoformat(),
            tasks=tasks,
            preferences_summary=pref_snapshot,
            rationale=[f"llm_generated: {len(tasks)} tasks", action_summary[:120]],
        )

    def _parse_llm_plan(
        self,
        text: str,
        preferences: dict[str, Any],
    ) -> list[CrawlTask]:
        """Parse the LLM JSON array into CrawlTask objects.

        Returns an empty list when parsing fails or the output is structurally
        invalid, so the caller can detect failure and fall back to rule mode.
        """
        try:
            clean = text.strip().strip("```json").strip("```").strip()
            raw: list[dict[str, Any]] = json.loads(clean)
            if not isinstance(raw, list) or not raw:
                return []

            tasks: list[CrawlTask] = []
            for entry in raw:
                platform = str(entry.get("platform", "")).strip().lower()
                pool = str(entry.get("pool", "")).strip().lower()
                query = str(entry.get("query", "")).strip()
                reason = str(entry.get("reason", "")).strip()

                if platform not in self.PLATFORM_LAYERS:
                    continue
                if pool not in ("precision", "exploration"):
                    continue
                if not query:
                    continue

                tasks.append(
                    CrawlTask(
                        platform=platform,
                        source_layer=self.PLATFORM_LAYERS[platform],
                        pool=pool,
                        query=query,
                        max_results=self.PLATFORM_MAX_RESULTS.get(platform, 3),
                        metadata={"reason": reason, "llm_generated": True},
                    )
                )

            return tasks
        except (json.JSONDecodeError, TypeError, KeyError):
            return []

    def _summarise_actions(self, actions: list[sqlite3.Row]) -> str:
        """Produce a compact text summary of recent user actions for the LLM."""
        if not actions:
            return "No recent actions recorded."

        open_titles = [
            row["item_title"] for row in actions if row["action"] == "open" and row["item_title"]
        ][:5]
        save_titles = [
            row["item_title"] for row in actions if row["action"] == "save" and row["item_title"]
        ][:3]
        skip_titles = [
            row["item_title"]
            for row in actions
            if row["action"].startswith("skip") and row["item_title"]
        ][:5]

        parts: list[str] = []
        if open_titles:
            parts.append("Opened: " + " | ".join(open_titles))
        if save_titles:
            parts.append("Saved: " + " | ".join(save_titles))
        if skip_titles:
            parts.append("Skipped: " + " | ".join(skip_titles))

        counts = {
            "open": sum(1 for r in actions if r["action"] == "open"),
            "save": sum(1 for r in actions if r["action"] == "save"),
            "skip": sum(1 for r in actions if r["action"].startswith("skip")),
        }
        parts.append(
            f"Totals — open:{counts['open']} save:{counts['save']} skip:{counts['skip']}"
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Rule-based planning (original logic, kept as stable fallback)
    # ------------------------------------------------------------------

    def _rule_build_daily_plan(
        self,
        preferences: dict[str, Any],
        recent_actions: list[sqlite3.Row],
    ) -> DailyPlan:
        """Deterministic rule-based crawl plan (original implementation)."""
        pref = preferences
        actions = recent_actions

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
                        "llm_generated": False,
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
                        "llm_generated": False,
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
        filtered = [
            query for query in base_queries
            if not self._contains_suppressed_topic(query, suppressed_topics)
        ]
        if len(filtered) < 3:
            for topic in boosted_topics:
                candidate = f"{topic} open source"
                if candidate not in filtered and not self._contains_suppressed_topic(
                    candidate, suppressed_topics
                ):
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
