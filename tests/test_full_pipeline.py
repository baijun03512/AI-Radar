"""End-to-end phase-4 integration test."""
from __future__ import annotations

import json
from pathlib import Path

from ai_radar.agents import (
    ChatAgent,
    CrawlerAgent,
    MemoryAgent,
    NoveltyScorerAgent,
    OrchestratorAgent,
    RecommenderAgent,
)
from ai_radar.data import get_db, init_db
from ai_radar.runtime.tool_registry import Tool, ToolRegistry
from ai_radar.skills import SkillManager, SkillStorage


def build_registry() -> ToolRegistry:
    """Build one deterministic registry for the full pipeline."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="query_notion_wiki",
            description="wiki",
            input_schema={"type": "object", "properties": {}},
            handler=lambda query="", max_results=10: json.dumps(
                [{"page_id": "p1", "url": "https://notion.test/1", "name": "AgentKit", "tags": ["industry"]}],
                ensure_ascii=False,
            ),
        )
    )
    registry.register(
        Tool(
            name="search_arxiv",
            description="arxiv",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda query="", max_results=10, days=90: json.dumps(
                [{
                    "item_id": f"arxiv-{query}",
                    "title": f"Paper about {query}",
                    "summary": "benchmark and method details with agent innovation",
                    "source_platform": "arxiv",
                    "source_layer": "academic",
                    "source_url": "https://arxiv.test/1",
                    "published_at": "2026-04-20T00:00:00+00:00",
                    "fetched_at": "2026-04-27T00:00:00+00:00",
                }],
                ensure_ascii=False,
            ),
        )
    )
    registry.register(
        Tool(
            name="search_product_hunt",
            description="ph",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda query="", max_results=10: json.dumps(
                [{
                    "item_id": f"ph-{query or 'launch'}",
                    "title": f"Launch {query or 'launch'}",
                    "summary": "production release for teams using agent workflows",
                    "source_platform": "product_hunt",
                    "source_layer": "industry",
                    "source_url": "https://ph.test/1",
                    "published_at": "2026-04-25T00:00:00+00:00",
                    "fetched_at": "2026-04-27T00:00:00+00:00",
                }],
                ensure_ascii=False,
            ),
        )
    )
    registry.register(
        Tool(
            name="search_reddit",
            description="reddit",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda query="", subreddit="MachineLearning", max_results=10: json.dumps(
                [{
                    "item_id": f"reddit-{query}",
                    "title": f"Thread {query}",
                    "summary": "real user feedback on agent workflows in production",
                    "source_platform": "reddit",
                    "source_layer": "community",
                    "source_url": "https://reddit.test/1",
                    "published_at": "2026-04-24T00:00:00+00:00",
                    "fetched_at": "2026-04-27T00:00:00+00:00",
                }],
                ensure_ascii=False,
            ),
        )
    )
    registry.register(
        Tool(
            name="upsert_notion_wiki",
            description="upsert",
            input_schema={"type": "object", "properties": {}},
            handler=lambda name, one_liner, tags=None: json.dumps({"page_id": "new-page"}),
        )
    )
    return registry


def test_full_pipeline_runs_end_to_end(tmp_path: Path) -> None:
    """Run the phase-4 pipeline end to end from planning to memory."""
    db_path = tmp_path / "radar.db"
    init_db(db_path)
    registry = build_registry()
    preferences = {
        "interests": ["AgentKit", "AI agents"],
        "preferred_platforms": ["product_hunt", "arxiv", "reddit"],
        "exploration_ratio": 0.3,
        "feed_size": 6,
    }

    orchestrator = OrchestratorAgent(db_path=str(db_path))
    plan = orchestrator.build_daily_plan(preferences)

    skill_manager = SkillManager(storage=SkillStorage(tmp_path / "skills"))
    crawler = CrawlerAgent(registry=registry, skill_manager=skill_manager, cache_dir=tmp_path / "cache")
    crawl_result = crawler.crawl(plan.tasks[:3])
    assert crawl_result.items

    scorer = NoveltyScorerAgent()
    scored = scorer.score_batch(crawl_result.items)
    assert scored

    recommender = RecommenderAgent(db_path=str(db_path))
    feed_result = recommender.build_feed(scored, preferences=preferences)
    assert feed_result.feed.precision_pool or feed_result.feed.exploration_pool

    selected = (
        feed_result.feed.precision_pool[0]
        if feed_result.feed.precision_pool
        else feed_result.feed.exploration_pool[0]
    )
    chat = ChatAgent(registry)
    chat_result = chat.answer_query(f"How does {selected.title} work?")
    payload = chat.build_memory_payload(
        product_id=selected.item_id,
        product_name=selected.title,
        query=f"How does {selected.title} work?",
        result=chat_result,
    )

    memory = MemoryAgent(tmp_path / "memory")
    stored = memory.process_payload(payload, registry=registry, write_notion=True)
    assert stored.quality_score >= 3.0
    assert stored.notion_written

    conn = get_db(db_path)
    history_rows = conn.execute("SELECT COUNT(*) AS n FROM feed_history").fetchone()
    conn.close()
    assert history_rows["n"] >= 1
