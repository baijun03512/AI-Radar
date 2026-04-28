"""Runtime learning loop: analyze logs, detect patterns, and evolve memory weights."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..data import get_db, init_db
from ..skills import Skill, SkillManager

LEARNING_LOOP_PROMPT = """You are the runtime learning module for AI Product Radar.
Inputs:
- recent execution logs
- historical skills
- memory usage signals

Decide whether there is durable learning worth persisting:
1. repeated chat question patterns -> create response template skills
2. unstable skills with poor success rate -> flag for regeneration
3. wiki pages with repeated recall -> increase weight

Only persist new learning when confidence is at least 0.8.
Return concise reasons for each learning decision.
"""


@dataclass
class AgentLogSummary:
    """Aggregated metrics for one agent or tool."""

    key: str
    runs: int
    success_rate: float
    avg_duration_ms: float


@dataclass
class ExecutionAnalysis:
    """High-level summary of recent execution logs."""

    total_logs: int
    by_agent: list[AgentLogSummary] = field(default_factory=list)
    by_tool: list[AgentLogSummary] = field(default_factory=list)
    failing_tools: list[str] = field(default_factory=list)


@dataclass
class ResponsePattern:
    """A detected repeated user-question pattern."""

    pattern_key: str
    sample_query: str
    count: int
    confidence: float


@dataclass
class MemoryWeightUpdate:
    """One wiki-memory weight evolution event."""

    name: str
    recall_count: int
    old_weight: float
    new_weight: float


@dataclass
class LearningCycleResult:
    """Combined output of one runtime learning pass."""

    execution_analysis: ExecutionAnalysis
    created_skills: list[str] = field(default_factory=list)
    flagged_skills: list[str] = field(default_factory=list)
    memory_updates: list[MemoryWeightUpdate] = field(default_factory=list)


class ExecutionLogAnalyzer:
    """Summarize recent runtime execution from the SQLite observability table."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path
        init_db(db_path)

    def analyze_recent_logs(self, limit: int = 200) -> ExecutionAnalysis:
        """Aggregate recent logs by agent and by tool."""
        conn = get_db(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT agent_name, tool_called, tool_success, duration_ms
                FROM agent_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()

        by_agent: dict[str, list[tuple[int, int]]] = defaultdict(list)
        by_tool: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for row in rows:
            by_agent[row["agent_name"]].append((row["tool_success"], row["duration_ms"] or 0))
            if row["tool_called"]:
                by_tool[row["tool_called"]].append((row["tool_success"], row["duration_ms"] or 0))

        failing_tools: list[str] = []
        tool_summaries = [self._summarize_group(key, values) for key, values in by_tool.items()]
        for summary in tool_summaries:
            if summary.runs >= 2 and summary.success_rate < 0.8:
                failing_tools.append(summary.key)

        return ExecutionAnalysis(
            total_logs=len(rows),
            by_agent=[self._summarize_group(key, values) for key, values in by_agent.items()],
            by_tool=tool_summaries,
            failing_tools=sorted(failing_tools),
        )

    def _summarize_group(self, key: str, values: list[tuple[int, int]]) -> AgentLogSummary:
        """Compute success rate and average duration for a grouped key."""
        runs = len(values)
        success_rate = sum(success for success, _ in values) / runs if runs else 0.0
        avg_duration = sum(duration for _, duration in values) / runs if runs else 0.0
        return AgentLogSummary(
            key=key,
            runs=runs,
            success_rate=round(success_rate, 3),
            avg_duration_ms=round(avg_duration, 2),
        )


class RuntimeLearningAgent:
    """Analyze logs and memory to persist durable runtime learning."""

    def __init__(
        self,
        *,
        skill_manager: SkillManager,
        db_path: str | None = None,
        memory_dir: str | Path = "data/memory",
        min_confidence: float = 0.8,
    ) -> None:
        self.skill_manager = skill_manager
        self.db_path = db_path
        self.analyzer = ExecutionLogAnalyzer(db_path=db_path)
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.min_confidence = min_confidence

    def run_learning_cycle(self) -> LearningCycleResult:
        """Run one learning pass over recent logs, sessions, and wiki cache."""
        analysis = self.analyzer.analyze_recent_logs()
        patterns = self.detect_response_patterns()
        created_skills = self.create_response_template_skills(patterns)
        flagged_skills = [skill.skill_id for skill in self.skill_manager.skills_requiring_healing()]
        memory_updates = self.evolve_memory_weights()
        return LearningCycleResult(
            execution_analysis=analysis,
            created_skills=created_skills,
            flagged_skills=flagged_skills,
            memory_updates=memory_updates,
        )

    def detect_response_patterns(self, min_occurrences: int = 3) -> list[ResponsePattern]:
        """Detect repeated user questions from memory session files."""
        counts: Counter[str] = Counter()
        samples: dict[str, str] = {}
        for payload in self._session_payloads():
            for turn in payload.get("conversation", []):
                if turn.get("role") != "user":
                    continue
                normalized = self._normalize_query(turn.get("content", ""))
                if not normalized:
                    continue
                counts[normalized] += 1
                samples.setdefault(normalized, turn.get("content", ""))

        patterns: list[ResponsePattern] = []
        for key, count in counts.items():
            if count < min_occurrences:
                continue
            confidence = min(0.95, 0.7 + 0.1 * (count - 2))
            patterns.append(
                ResponsePattern(
                    pattern_key=self._pattern_key(key),
                    sample_query=samples[key],
                    count=count,
                    confidence=round(confidence, 3),
                )
            )
        patterns.sort(key=lambda item: (item.count, item.confidence), reverse=True)
        return patterns

    def create_response_template_skills(self, patterns: list[ResponsePattern]) -> list[str]:
        """Persist response template skills for confident repeated patterns."""
        created: list[str] = []
        for pattern in patterns:
            if not self._passes_quality_filter(pattern.confidence):
                continue
            skill = self.skill_manager.learn_response_template_skill(
                pattern_key=pattern.pattern_key,
                sample_query=pattern.sample_query,
                template=(
                    "Answer this recurring question with a three-part structure: "
                    "summary, key evidence, and practical takeaway."
                ),
                confidence=pattern.confidence,
            )
            if skill is not None:
                created.append(skill.skill_id)
        return created

    def evolve_memory_weights(self) -> list[MemoryWeightUpdate]:
        """Update local wiki cache weights based on repeated session recall."""
        cache_path = self.memory_dir / "wiki_cache.json"
        if not cache_path.exists():
            return []

        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        mention_counts: Counter[str] = Counter()
        for payload in self._session_payloads():
            product_name = payload.get("product_name", "")
            if product_name:
                mention_counts[product_name] += 1

        updates: list[MemoryWeightUpdate] = []
        for entry in cache:
            name = entry.get("name") or ""
            if not name:
                continue
            recalls = mention_counts.get(name, 0)
            old_weight = float(entry.get("weight", 1.0))
            old_recall = int(entry.get("recall_count", 0))
            if recalls == 0 and old_recall == 0:
                continue
            new_recall = old_recall + recalls
            new_weight = round(min(3.0, 1.0 + 0.2 * new_recall), 2)
            entry["recall_count"] = new_recall
            entry["weight"] = new_weight
            updates.append(
                MemoryWeightUpdate(
                    name=name,
                    recall_count=new_recall,
                    old_weight=old_weight,
                    new_weight=new_weight,
                )
            )

        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        return updates

    def _session_payloads(self) -> list[dict[str, Any]]:
        """Load all saved memory session payloads."""
        session_dir = self.memory_dir / "sessions"
        if not session_dir.exists():
            return []
        payloads: list[dict[str, Any]] = []
        for path in sorted(session_dir.glob("*.json")):
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        return payloads

    def _normalize_query(self, text: str) -> str:
        """Normalize user queries for simple pattern counting."""
        lowered = text.lower().strip()
        lowered = re.sub(r"https?://\S+", "", lowered)
        lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered).strip()
        return lowered

    def _pattern_key(self, text: str) -> str:
        """Convert a normalized query into a stable skill id suffix."""
        return re.sub(r"\s+", "_", text)[:60]

    def _passes_quality_filter(self, confidence: float) -> bool:
        """Apply the minimum-confidence learning filter."""
        return confidence >= self.min_confidence
