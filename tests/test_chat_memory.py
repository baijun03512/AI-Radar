"""Phase-4 tests for chat and memory agents."""
from __future__ import annotations

import json
from pathlib import Path

from ai_radar.agents import ChatAgent, MemoryAgent
from ai_radar.runtime.tool_registry import Tool, ToolRegistry


def build_registry() -> ToolRegistry:
    """Create a fake registry with chat/memory-relevant tools."""
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
            name="search_product_hunt",
            description="ph",
            input_schema={"type": "object", "properties": {}},
            handler=lambda query="", max_results=2: json.dumps(
                [{
                    "item_id": "ph1",
                    "title": f"Launch {query}",
                    "summary": "production release for teams",
                    "source_platform": "product_hunt",
                    "source_layer": "industry",
                    "source_url": "https://ph.test/1",
                }],
                ensure_ascii=False,
            ),
        )
    )
    registry.register(
        Tool(
            name="search_arxiv",
            description="arxiv",
            input_schema={"type": "object", "properties": {}},
            handler=lambda query="", max_results=2, days=90: json.dumps(
                [{
                    "item_id": "a1",
                    "title": f"Paper {query}",
                    "summary": "benchmark and method details",
                    "source_platform": "arxiv",
                    "source_layer": "academic",
                    "source_url": "https://arxiv.test/1",
                }],
                ensure_ascii=False,
            ),
        )
    )
    registry.register(
        Tool(
            name="search_reddit",
            description="reddit",
            input_schema={"type": "object", "properties": {}},
            handler=lambda query="", subreddit="MachineLearning", max_results=2: json.dumps(
                [{
                    "item_id": "r1",
                    "title": f"Thread {query}",
                    "summary": "real user feedback and issues",
                    "source_platform": "reddit",
                    "source_layer": "community",
                    "source_url": "https://reddit.test/1",
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


def test_chat_agent_detects_comparison_intent() -> None:
    """Comparison queries should be routed to comparison intent."""
    agent = ChatAgent(build_registry())
    assert agent.detect_intent("Compare AgentKit vs Cursor for AI coding") == "comparison"


def test_chat_agent_produces_multi_source_answer_and_memory_payload() -> None:
    """Chat answer should include multiple sources and be convertible to memory payload."""
    agent = ChatAgent(build_registry())
    result = agent.answer_query("How does AgentKit work under the hood?")

    assert result.intent_type == "deep_dive"
    assert len(result.sources_used) >= 2
    assert "AgentKit" in result.answer

    payload = agent.build_memory_payload(
        product_id="agentkit",
        product_name="AgentKit",
        query="How does AgentKit work under the hood?",
        result=result,
    )
    assert payload.product_name == "AgentKit"
    assert payload.intent_type == "deep_dive"


def test_memory_agent_compiles_and_scores_wiki_page(tmp_path: Path) -> None:
    """Memory agent should compile a wiki page with a usable quality score."""
    chat_agent = ChatAgent(build_registry())
    result = chat_agent.answer_query("Tell me about AgentKit")
    payload = chat_agent.build_memory_payload(
        product_id="agentkit",
        product_name="AgentKit",
        query="Tell me about AgentKit",
        result=result,
    )

    memory = MemoryAgent(tmp_path)
    processed = memory.process_payload(payload)
    assert processed.quality_score >= 3.0
    assert processed.wiki_page.name == "AgentKit"
    assert processed.wiki_page.chat_notes


def test_memory_agent_warms_wiki_cache_and_writes_file(tmp_path: Path) -> None:
    """Wiki cache warmup should fetch summaries and store a local cache file."""
    memory = MemoryAgent(tmp_path)
    entries = memory.warm_wiki_cache(build_registry(), max_results=5)
    assert len(entries) == 1
    assert (tmp_path / "wiki_cache.json").exists()


def test_memory_agent_merges_second_session_without_error(tmp_path: Path) -> None:
    """Second session for same product should merge without AttributeError on nested dataclasses."""
    chat_agent = ChatAgent(build_registry())

    def make_payload(query: str) -> object:
        result = chat_agent.answer_query(query)
        return chat_agent.build_memory_payload(
            product_id="agentkit",
            product_name="AgentKit",
            query=query,
            result=result,
        )

    memory = MemoryAgent(tmp_path)
    memory.process_payload(make_payload("How does AgentKit work?"))
    result2 = memory.process_payload(make_payload("What are AgentKit's limitations?"))
    assert result2.wiki_page.name == "AgentKit"
    assert result2.quality_score >= 1.0


def test_memory_agent_queues_failed_notion_writes(tmp_path: Path) -> None:
    """Failed notion writes should be queued locally for retry."""
    chat_agent = ChatAgent(build_registry())
    result = chat_agent.answer_query("Tell me about AgentKit")
    payload = chat_agent.build_memory_payload(
        product_id="agentkit",
        product_name="AgentKit",
        query="Tell me about AgentKit",
        result=result,
    )

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="upsert_notion_wiki",
            description="broken",
            input_schema={"type": "object", "properties": {}},
            handler=lambda name, one_liner, tags=None: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )
    memory = MemoryAgent(tmp_path)
    processed = memory.process_payload(payload, registry=registry, write_notion=True)
    assert not processed.notion_written
    assert processed.queued_for_retry
    assert (tmp_path / "pending_writes.json").exists()
