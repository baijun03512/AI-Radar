"""Phase-6 tests for the FastAPI layer."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ai_radar.api.main import create_app
from ai_radar.api.services import AppServices
from ai_radar.runtime.observability import LogEntry, Observability
from ai_radar.runtime.tool_registry import Tool, ToolRegistry


def build_registry() -> ToolRegistry:
    """Create a deterministic registry for API tests."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="query_notion_wiki",
            description="wiki",
            input_schema={"type": "object", "properties": {}},
            handler=lambda query="", max_results=10: json.dumps(
                [
                    {
                        "page_id": "p1",
                        "url": "https://notion.test/1",
                        "name": "AgentKit",
                        "one_liner": "Agent workflow toolkit",
                        "tags": ["industry"],
                        "weight": 1.8,
                        "recall_count": 3,
                    }
                ],
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
                [
                    {
                        "item_id": f"arxiv-{query}",
                        "title": f"Paper about {query}",
                        "summary": "benchmark and method details with agent innovation",
                        "source_platform": "arxiv",
                        "source_layer": "academic",
                        "source_url": "https://arxiv.test/1",
                        "published_at": "2026-04-20T00:00:00+00:00",
                        "fetched_at": "2026-04-27T00:00:00+00:00",
                    }
                ],
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
                [
                    {
                        "item_id": f"ph-{query or 'launch'}",
                        "title": f"Launch {query or 'launch'}",
                        "summary": "production release for teams using agent workflows",
                        "source_platform": "product_hunt",
                        "source_layer": "industry",
                        "source_url": "https://ph.test/1",
                        "published_at": "2026-04-25T00:00:00+00:00",
                        "fetched_at": "2026-04-27T00:00:00+00:00",
                    }
                ],
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
                [
                    {
                        "item_id": f"reddit-{query}",
                        "title": f"Thread {query}",
                        "summary": "real user feedback on agent workflows in production",
                        "source_platform": "reddit",
                        "source_layer": "community",
                        "source_url": "https://reddit.test/1",
                        "published_at": "2026-04-24T00:00:00+00:00",
                        "fetched_at": "2026-04-27T00:00:00+00:00",
                    }
                ],
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
    registry.register(
        Tool(
            name="load_notion_preferences",
            description="load prefs",
            input_schema={"type": "object", "properties": {}},
            handler=lambda page_id="": json.dumps(
                {
                    "interests": ["remote agents"],
                    "preferred_platforms": ["arxiv"],
                    "exploration_ratio": 0.2,
                    "feed_size": 6,
                    "exploration_queries": ["remote query"],
                },
                ensure_ascii=False,
            ),
        )
    )
    registry.register(
        Tool(
            name="sync_notion_preferences",
            description="sync prefs",
            input_schema={"type": "object", "properties": {}},
            handler=lambda profile, page_id="": json.dumps({"ok": True, "profile": profile}, ensure_ascii=False),
        )
    )
    return registry


def build_client(tmp_path: Path) -> TestClient:
    """Build a test client with isolated app storage."""
    db_path = tmp_path / "radar.db"
    memory_dir = tmp_path / "memory"
    services = AppServices(
        registry=build_registry(),
        db_path=str(db_path),
        memory_dir=memory_dir,
        skill_dir=tmp_path / "skills",
        preferences_path=tmp_path / "preferences.json",
    )
    services.memory_agent.wiki_cache_path.write_text(
        json.dumps(
            [
                {
                    "name": "AgentKit",
                    "one_liner": "Agent workflow toolkit",
                    "tags": ["industry"],
                    "weight": 1.8,
                    "recall_count": 3,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    obs = Observability(db_path=str(db_path))
    obs.log(
        LogEntry(
            agent="crawler_agent",
            turn=1,
            tool_called="search_arxiv",
            tool_success=True,
            duration_ms=120,
        )
    )
    obs.close()
    app = create_app(services=services)
    return TestClient(app)


def build_services(tmp_path: Path) -> AppServices:
    """Build isolated services for direct helper-method tests."""
    db_path = tmp_path / "radar.db"
    memory_dir = tmp_path / "memory"
    services = AppServices(
        registry=build_registry(),
        db_path=str(db_path),
        memory_dir=memory_dir,
        skill_dir=tmp_path / "skills",
        preferences_path=tmp_path / "preferences.json",
    )
    services.memory_agent.wiki_cache_path.write_text(
        json.dumps(
            [
                {
                    "name": "AgentKit",
                    "one_liner": "Agent workflow toolkit with runtime orchestration",
                    "tags": ["industry", "agent-runtime"],
                    "weight": 1.8,
                    "recall_count": 3,
                },
                {
                    "name": "MCP",
                    "one_liner": "Standardized tool and server protocol layer",
                    "tags": ["industry", "tooling"],
                    "weight": 2.1,
                    "recall_count": 5,
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return services


def test_feed_endpoint_returns_precision_and_exploration_items(tmp_path: Path) -> None:
    """The feed endpoint should return a structured daily feed."""
    client = build_client(tmp_path)
    response = client.get("/api/feed")
    assert response.status_code == 200
    payload = response.json()
    assert payload["precision_pool"] or payload["exploration_pool"]
    first_item = (payload["precision_pool"] or payload["exploration_pool"])[0]
    assert first_item["source_type"] in {"academic", "industry", "community"}
    assert first_item["novelty_type"] in {"new", "update", "watch"}
    assert "tasks_executed" in payload["diagnostics"]


def test_feed_action_endpoint_records_user_behavior(tmp_path: Path) -> None:
    """Feed actions should be persisted through the API."""
    client = build_client(tmp_path)
    response = client.post(
        "/api/feed/agentkit/action",
        json={"action": "save", "item_title": "AgentKit", "one_liner": "Agent workflow toolkit", "pool_type": "precision", "source_type": "industry"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    saved_file = tmp_path / "memory" / "saved_items.json"
    assert saved_file.exists()


def test_chat_endpoint_streams_sse_events(tmp_path: Path) -> None:
    """Chat endpoint should respond as an SSE stream."""
    client = build_client(tmp_path)
    with client.stream(
        "POST",
        "/api/chat",
        json={"query": "How does AgentKit work?", "product_id": "agentkit", "product_name": "AgentKit"},
    ) as response:
        body = "".join(part for part in response.iter_text())
    assert response.status_code == 200
    assert "event: meta" in body
    assert "event: message" in body
    assert "event: done" in body
    assert "\"source_type\"" in body


def test_preferences_dashboard_and_wiki_endpoints(tmp_path: Path) -> None:
    """Preferences, dashboard, and wiki endpoints should all be reachable."""
    client = build_client(tmp_path)

    update = client.post("/api/preferences", json={"exploration_ratio": 0.4, "feed_size": 8})
    assert update.status_code == 200
    assert update.json()["exploration_ratio"] == 0.4

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert "skill_health" in dashboard.json()

    wiki = client.get("/api/wiki", params={"query": "AgentKit"})
    assert wiki.status_code == 200
    assert wiki.json()["items"][0]["name"] == "AgentKit"


def test_services_build_memory_brief_from_local_wiki_cache(tmp_path: Path) -> None:
    """Feed summarization helpers should extract a short relevant wiki-memory brief."""
    services = build_services(tmp_path)
    brief = services._build_memory_brief("AgentKit runtime")
    assert "AgentKit" in brief
    assert "Agent workflow toolkit" in brief


def test_services_can_load_preferences_from_notion_when_local_file_missing(tmp_path: Path) -> None:
    """Preferences should fall back to the mirrored Notion page when the local file is absent."""
    services = AppServices(
        registry=build_registry(),
        db_path=str(tmp_path / "radar.db"),
        memory_dir=tmp_path / "memory",
        skill_dir=tmp_path / "skills",
        preferences_path=tmp_path / "missing-preferences.json",
    )
    loaded = services.load_preferences()
    assert loaded["interests"] == ["remote agents"]
    assert loaded["feed_size"] == 6
    assert Path(services.preferences_path).exists()


def test_services_derive_lightweight_behavioral_preferences(tmp_path: Path) -> None:
    """Recent open/save/skip actions should evolve boosted and suppressed topics."""
    services = build_services(tmp_path)
    services.record_action(item_id="1", action="save", item_title="OpenAI Runtime Harness")
    services.record_action(item_id="2", action="open", item_title="Runtime SDK Workflow")
    services.record_action(item_id="3", action="save", item_title="Runtime Orchestration Layer")
    services.record_action(item_id="4", action="skip", item_title="Marketing Landing Page Builder")
    services.record_action(item_id="5", action="skip_future", item_title="Marketing Attribution Suite")

    updated = services.load_preferences()
    assert "runtime" in updated["boosted_topics"]
    assert "marketing" in updated["suppressed_topics"]
