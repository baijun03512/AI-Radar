"""Phase-4 tests for orchestrator and crawler agents."""
from __future__ import annotations

import json
from pathlib import Path

from ai_radar.agents import CrawlerAgent, OrchestratorAgent
from ai_radar.data import get_db, init_db
from ai_radar.runtime.observability import Observability
from ai_radar.runtime.tool_registry import Tool, ToolRegistry
from ai_radar.skills import SkillManager, SkillStorage


def build_registry() -> ToolRegistry:
    """Build fake crawler tools for agent tests."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="search_arxiv",
            description="fake arxiv",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda query, max_results=10, days=90: json.dumps(
                [
                    {
                        "item_id": f"arxiv-{query}",
                        "title": f"Paper about {query}",
                        "summary": "academic result",
                        "source_platform": "arxiv",
                        "source_layer": "学术层",
                        "source_url": "https://arxiv.test/1",
                        "published_at": "2026-04-27T00:00:00Z",
                        "fetched_at": "2026-04-27T01:00:00Z",
                    }
                ][:max_results]
            ),
        )
    )
    registry.register(
        Tool(
            name="search_product_hunt",
            description="fake ph",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda query="", max_results=10: json.dumps(
                [
                    {
                        "item_id": f"ph-{query or 'launch'}",
                        "title": f"Launch {query or 'launch'}",
                        "summary": "industrial result",
                        "source_platform": "product_hunt",
                        "source_layer": "工业层",
                        "source_url": "https://ph.test/1",
                        "published_at": "2026-04-27T00:00:00Z",
                        "fetched_at": "2026-04-27T01:00:00Z",
                    }
                ][:max_results]
            ),
        )
    )
    registry.register(
        Tool(
            name="search_reddit",
            description="fake reddit",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda query="AI", subreddit="MachineLearning", max_results=10: json.dumps(
                [
                    {
                        "item_id": f"reddit-{query}",
                        "title": f"Thread {query}",
                        "summary": "community result",
                        "source_platform": "reddit",
                        "source_layer": "社区层",
                        "source_url": "https://reddit.test/1",
                        "published_at": "2026-04-27T00:00:00Z",
                        "fetched_at": "2026-04-27T01:00:00Z",
                    }
                ][:max_results]
            ),
        )
    )
    registry.register(
        Tool(
            name="failing_tool",
            description="always fail",
            input_schema={"type": "object", "properties": {}},
            handler=lambda query="", max_results=10: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )
    return registry


def build_skill_manager(tmp_path: Path) -> SkillManager:
    """Create a temp-backed skill manager for tests."""
    return SkillManager(storage=SkillStorage(tmp_path / "skills"))


def test_orchestrator_builds_daily_plan_from_preferences(tmp_path: Path) -> None:
    """Daily plan contains both precision and exploration tasks."""
    db_path = tmp_path / "radar.db"
    init_db(db_path)
    agent = OrchestratorAgent(db_path=str(db_path))
    plan = agent.build_daily_plan(
        {
            "interests": ["coding agents", "AI search"],
            "preferred_platforms": ["product_hunt", "reddit"],
            "exploration_ratio": 0.3,
        }
    )

    assert plan.plan_date
    assert any(task.pool == "precision" for task in plan.tasks)
    assert any(task.pool == "exploration" for task in plan.tasks)
    assert plan.preferences_summary["exploration_ratio"] == 0.3


def test_crawler_executes_plan_and_returns_structured_items(tmp_path: Path) -> None:
    """Crawler executes orchestrated tasks and emits structured contracts."""
    registry = build_registry()
    skill_manager = build_skill_manager(tmp_path)
    crawler = CrawlerAgent(
        registry=registry,
        skill_manager=skill_manager,
        cache_dir=tmp_path / "cache",
    )
    plan = OrchestratorAgent().build_daily_plan(
        {
            "interests": ["coding agents"],
            "preferred_platforms": ["arxiv", "reddit", "product_hunt"],
        },
    )

    result = crawler.crawl(plan.tasks[:3])

    assert result.tasks_executed == 3
    assert result.report.total_items == 3
    assert {item.source_platform for item in result.items} == {"arxiv", "reddit", "product_hunt"}


def test_crawler_falls_back_to_cache_when_tool_fails(tmp_path: Path) -> None:
    """Failed tasks reuse the latest cached platform results."""
    registry = build_registry()
    skill_manager = build_skill_manager(tmp_path)
    crawler = CrawlerAgent(
        registry=registry,
        skill_manager=skill_manager,
        cache_dir=tmp_path / "cache",
    )
    task = OrchestratorAgent().build_daily_plan({"preferred_platforms": ["arxiv"]}).tasks[0]
    first = crawler.crawl([task])
    assert first.report.total_items == 1

    failing_registry = build_registry()
    skill = skill_manager.match_skill(skill_type="crawler", platform="arxiv")
    assert skill is not None
    skill.tool_name = "failing_tool"
    skill_manager.save(skill)

    failing_crawler = CrawlerAgent(
        registry=failing_registry,
        skill_manager=skill_manager,
        cache_dir=tmp_path / "cache",
    )
    second = failing_crawler.crawl([task])

    assert second.report.total_items == 1
    assert "arxiv" in second.report.cached_platforms


def test_crawler_logs_to_observability(tmp_path: Path) -> None:
    """Crawler writes task-level observability logs."""
    db_path = tmp_path / "radar.db"
    registry = build_registry()
    skill_manager = build_skill_manager(tmp_path)
    observability = Observability(db_path=str(db_path))
    crawler = CrawlerAgent(
        registry=registry,
        skill_manager=skill_manager,
        observability=observability,
        cache_dir=tmp_path / "cache",
    )
    task = OrchestratorAgent().build_daily_plan({"preferred_platforms": ["reddit"]}).tasks[0]
    crawler.crawl([task])

    conn = get_db(db_path)
    rows = conn.execute(
        "SELECT agent_name, tool_called, tool_success FROM agent_logs ORDER BY id"
    ).fetchall()
    conn.close()
    observability.close()

    assert rows[0]["agent_name"] == "crawler_agent"
    assert rows[0]["tool_called"] == "search_reddit"
    assert rows[0]["tool_success"] == 1
