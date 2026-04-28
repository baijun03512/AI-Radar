"""Phase-3 tests for the local skill system."""
from __future__ import annotations

import json
from pathlib import Path

from ai_radar.runtime.tool_registry import Tool, ToolRegistry
from ai_radar.skills import SKILL_JSON_SCHEMA, Skill, SkillManager, SkillStorage


def build_registry() -> ToolRegistry:
    """Build a small registry for skill tests."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="search_arxiv",
            description="fake arxiv",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda query, max_results=10, days=90: json.dumps(
                [{"title": query, "max_results": max_results, "days": days}]
            ),
        )
    )
    registry.register(
        Tool(
            name="search_product_hunt",
            description="fake ph",
            input_schema={"type": "object", "properties": {}},
            handler=lambda max_results=10: json.dumps([{"title": "demo", "max_results": max_results}]),
        )
    )
    registry.register(
        Tool(
            name="search_reddit",
            description="fake reddit",
            input_schema={"type": "object", "properties": {}},
            handler=lambda query="AI", subreddit="MachineLearning", max_results=10: json.dumps(
                [{"query": query, "subreddit": subreddit, "max_results": max_results}]
            ),
        )
    )
    registry.register(
        Tool(
            name="always_fail",
            description="always fails",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )
    return registry


def build_manager(tmp_path: Path) -> SkillManager:
    """Create a manager backed by a temp skills directory."""
    return SkillManager(storage=SkillStorage(tmp_path), heal_threshold=0.8, min_usage_for_heal=3)


def test_skill_storage_round_trip(tmp_path: Path) -> None:
    """Skills persist as JSON and load back cleanly."""
    storage = SkillStorage(tmp_path)
    skill = Skill(
        skill_id="crawler_demo_v1",
        skill_type="crawler",
        platform="demo",
        source_layer="社区层",
        tool_name="search_reddit",
        description="demo skill",
        logic="do the demo thing",
    )
    storage.save(skill)

    loaded = storage.load("crawler_demo_v1")
    assert loaded.skill_id == skill.skill_id
    assert loaded.tool_name == "search_reddit"


def test_bootstrap_initial_skills_creates_three_seed_skills(tmp_path: Path) -> None:
    """The manager creates the three required crawler skills when tools exist."""
    manager = build_manager(tmp_path)
    created = manager.ensure_initial_crawler_skills(build_registry())

    assert len(created) == 3
    assert {skill.platform for skill in created} == {"arxiv", "product_hunt", "reddit"}
    assert len(manager.all_skills()) == 3


def test_match_and_execute_reuses_existing_skill(tmp_path: Path) -> None:
    """Second execution reuses the same matched skill and updates usage stats."""
    manager = build_manager(tmp_path)
    registry = build_registry()
    manager.ensure_initial_crawler_skills(registry)

    skill = manager.match_skill(skill_type="crawler", platform="arxiv")
    assert skill is not None

    first = manager.execute_skill(skill.skill_id, registry, skill_input={"query": "agents"})
    second = manager.execute_skill(skill.skill_id, registry, skill_input={"query": "agents"})

    updated = manager.get(skill.skill_id)
    assert first.success and second.success
    assert updated.usage_count == 2
    assert updated.success_rate == 1.0


def test_runtime_learning_creates_new_skill_when_confident(tmp_path: Path) -> None:
    """Successful execution can be turned into a runtime-learned crawler skill."""
    manager = build_manager(tmp_path)

    learned = manager.learn_crawler_skill(
        platform="HackerNews",
        source_layer="社区层",
        tool_name="fetch_hn",
        description="crawl hn",
        logic="search launch posts",
        input_template={"max_results": 5},
        confidence=0.92,
    )

    assert learned is not None
    assert learned.created_by == "runtime_learning"
    assert manager.get("crawler_hackernews_v1").tool_name == "fetch_hn"


def test_runtime_execution_can_auto_learn_new_skill(tmp_path: Path) -> None:
    """A successful direct tool run can persist a new crawler skill automatically."""
    manager = build_manager(tmp_path)
    registry = build_registry()

    result = manager.execute_tool_with_runtime_learning(
        registry=registry,
        platform="arxiv_custom",
        source_layer="学术层",
        tool_name="search_arxiv",
        tool_input={"query": "agent memory", "max_results": 3},
        description="custom arxiv crawler",
        logic="search a custom academic slice",
        confidence=0.95,
    )

    assert result.success
    assert not result.reused
    assert manager.get("crawler_arxiv_custom_v1").input_template["query"] == "agent memory"


def test_runtime_learning_skips_low_confidence_skill(tmp_path: Path) -> None:
    """Low-confidence learning attempts should not create persisted skills."""
    manager = build_manager(tmp_path)
    learned = manager.learn_crawler_skill(
        platform="NoisySite",
        source_layer="社区层",
        tool_name="fetch_noise",
        description="crawl noise",
        logic="do not trust this yet",
        confidence=0.4,
    )
    assert learned is None
    assert manager.all_skills() == []


def test_self_healing_triggers_when_success_rate_drops(tmp_path: Path) -> None:
    """Repeated failures flag a skill for regeneration."""
    manager = build_manager(tmp_path)
    registry = build_registry()
    failing = Skill(
        skill_id="crawler_fail_v1",
        skill_type="crawler",
        platform="fail",
        source_layer="工业层",
        tool_name="always_fail",
        description="failing skill",
        logic="always fail",
    )
    manager.save(failing)

    for _ in range(3):
        result = manager.execute_skill("crawler_fail_v1", registry)
        assert not result.success

    updated = manager.get("crawler_fail_v1")
    assert updated.heal_required
    assert updated.success_rate == 0.0
    assert manager.skills_requiring_healing()[0].skill_id == "crawler_fail_v1"


def test_skill_json_schema_covers_required_fields() -> None:
    """The explicit JSON schema declares the required MVP fields."""
    required = set(SKILL_JSON_SCHEMA["required"])
    assert {"skill_id", "skill_type", "platform", "tool_name", "logic"}.issubset(required)


def test_regenerate_skill_bumps_version_and_clears_heal_flag(tmp_path: Path) -> None:
    """Regeneration advances the version and clears the heal-required state."""
    manager = build_manager(tmp_path)
    skill = Skill(
        skill_id="crawler_fixme_v1",
        skill_type="crawler",
        platform="fixme",
        source_layer="工业层",
        tool_name="always_fail",
        description="broken",
        logic="old logic",
        heal_required=True,
        consecutive_failures=2,
    )
    manager.save(skill)

    regenerated = manager.regenerate_skill(
        "crawler_fixme_v1",
        logic="new logic",
        input_template={"query": "fresh"},
    )
    assert regenerated.version == 2
    assert regenerated.logic == "new logic"
    assert not regenerated.heal_required
    assert regenerated.consecutive_failures == 0
