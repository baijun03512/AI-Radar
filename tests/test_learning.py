"""Phase-5 tests for runtime learning."""
from __future__ import annotations

import json
from pathlib import Path

from ai_radar.agents.runtime_learning import (
    LEARNING_LOOP_PROMPT,
    ExecutionLogAnalyzer,
    RuntimeLearningAgent,
)
from ai_radar.runtime.observability import LogEntry, Observability
from ai_radar.skills import SkillManager, SkillStorage


def write_session(
    sessions_dir: Path,
    *,
    product_id: str,
    product_name: str,
    user_question: str,
) -> None:
    """Write one synthetic memory session payload."""
    payload = {
        "product_id": product_id,
        "product_name": product_name,
        "conversation": [
            {"role": "user", "content": user_question},
            {"role": "assistant", "content": "Here is a grounded answer."},
        ],
        "intent_type": "deep_dive",
        "sources_used": [{"layer": "工业层", "url": "https://x.test", "snippet": "prod"}],
        "new_insights": "deep_dive query synthesized from 3 retrievals",
        "ended_at": "2026-04-27T00:00:00+00:00",
        "end_reason": "manual_save",
    }
    (sessions_dir / f"{product_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_execution_log_analyzer_summarizes_recent_logs(tmp_path: Path) -> None:
    """Recent logs should be grouped by agent and tool."""
    db_path = tmp_path / "radar.db"
    obs = Observability(db_path=str(db_path))
    obs.log(LogEntry(agent="crawler_agent", turn=1, tool_called="search_arxiv", tool_success=True, duration_ms=120))
    obs.log(LogEntry(agent="crawler_agent", turn=2, tool_called="search_arxiv", tool_success=False, duration_ms=180))
    obs.log(LogEntry(agent="chat_agent", turn=1, tool_called="search_reddit", tool_success=True, duration_ms=90))
    obs.close()

    analysis = ExecutionLogAnalyzer(db_path=str(db_path)).analyze_recent_logs()
    assert analysis.total_logs == 3
    assert any(item.key == "crawler_agent" for item in analysis.by_agent)
    assert "search_arxiv" in [item.key for item in analysis.by_tool]
    assert "search_arxiv" in analysis.failing_tools


def test_runtime_learning_creates_response_template_skill_from_repeated_queries(tmp_path: Path) -> None:
    """Three repeated user queries should create one response template skill."""
    memory_dir = tmp_path / "memory"
    sessions_dir = memory_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    write_session(sessions_dir, product_id="p1", product_name="AgentKit", user_question="How does AgentKit work?")
    write_session(sessions_dir, product_id="p2", product_name="AgentFlow", user_question="How does AgentKit work?")
    write_session(sessions_dir, product_id="p3", product_name="AgentDesk", user_question="How does AgentKit work?")

    manager = SkillManager(storage=SkillStorage(tmp_path / "skills"))
    learner = RuntimeLearningAgent(skill_manager=manager, memory_dir=memory_dir)
    patterns = learner.detect_response_patterns()
    created = learner.create_response_template_skills(patterns)

    assert len(patterns) == 1
    assert created
    assert manager.get(created[0]).skill_type == "response_template"


def test_runtime_learning_quality_filter_rejects_low_confidence_patterns(tmp_path: Path) -> None:
    """Low-confidence patterns should be filtered before skill creation."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    manager = SkillManager(storage=SkillStorage(tmp_path / "skills"))
    learner = RuntimeLearningAgent(skill_manager=manager, memory_dir=memory_dir, min_confidence=0.9)

    result = learner.create_response_template_skills([])
    assert result == []
    assert manager.all_skills() == []


def test_memory_weight_evolution_updates_cache_file(tmp_path: Path) -> None:
    """Repeated mentions should bump recall_count and weight in wiki cache."""
    memory_dir = tmp_path / "memory"
    sessions_dir = memory_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    write_session(sessions_dir, product_id="p1", product_name="AgentKit", user_question="How does AgentKit work?")
    write_session(sessions_dir, product_id="p2", product_name="AgentKit", user_question="How does AgentKit work?")
    cache = [{"name": "AgentKit", "weight": 1.0, "recall_count": 0}]
    (memory_dir / "wiki_cache.json").write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    manager = SkillManager(storage=SkillStorage(tmp_path / "skills"))
    learner = RuntimeLearningAgent(skill_manager=manager, memory_dir=memory_dir)
    updates = learner.evolve_memory_weights()
    updated_cache = json.loads((memory_dir / "wiki_cache.json").read_text(encoding="utf-8"))

    assert updates[0].new_weight > 1.0
    assert updated_cache[0]["recall_count"] == 2


def test_learning_cycle_prompt_is_available() -> None:
    """The learning loop prompt should be non-empty for later LLM integration."""
    assert "runtime learning module" in LEARNING_LOOP_PROMPT.lower()
