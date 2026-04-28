"""Phase-2 unit tests for MCP-style tool modules."""
from __future__ import annotations

import json

from ai_radar.mcp_servers import build_default_registry
from ai_radar.mcp_servers import fetch_page_server, producthunt_server, reddit_server
from ai_radar.runtime.tool_registry import ToolRegistry


class _Response:
    """Tiny httpx/requests-like response double."""

    def __init__(
        self,
        text: str = "",
        payload: dict | None = None,
        url: str = "https://x.test",
    ) -> None:
        self.text = text
        self._payload = payload or {}
        self.url = url
        self.status_code = 200

    def raise_for_status(self) -> None:
        """Pretend the request succeeded."""
        return None

    def json(self) -> dict:
        """Return the configured JSON payload."""
        return self._payload


def test_build_default_registry_skips_credentialed_tools_without_env() -> None:
    """Default registry includes no-credential tools and skips missing credentials."""
    registry = build_default_registry(env={})
    assert {"search_arxiv", "search_reddit", "fetch_page"}.issubset(set(registry.names()))
    assert "search_product_hunt" not in registry.names()
    assert "query_notion_wiki" not in registry.names()


def test_fetch_page_extracts_readable_text(monkeypatch) -> None:
    """fetch_page removes scripts and returns title, description, and body text."""
    html = """
    <html><head><title>Demo</title><meta name="description" content="Short desc"></head>
    <body><script>bad()</script><main><h1>Hello</h1><p>AI radar page</p></main></body></html>
    """
    monkeypatch.setattr(
        fetch_page_server.httpx,
        "get",
        lambda *args, **kwargs: _Response(html, url=args[0]),
    )

    out = json.loads(fetch_page_server.fetch_page("https://example.com/demo"))
    assert out["title"] == "Demo"
    assert out["description"] == "Short desc"
    assert "AI radar page" in out["content"]
    assert "bad()" not in out["content"]


def test_producthunt_normalizes_graphql_posts(monkeypatch) -> None:
    """Product Hunt results are normalized into industrial-layer crawled items."""
    monkeypatch.setenv("PRODUCTHUNT_API_KEY", "test-token")
    payload = {
        "data": {
            "posts": {
                "edges": [
                    {
                        "node": {
                            "id": "p1",
                            "name": "AgentKit",
                            "tagline": "Build agents",
                            "description": "",
                            "url": "https://producthunt.com/posts/agentkit",
                            "website": "https://agentkit.test",
                            "slug": "agentkit",
                            "votesCount": 42,
                            "commentsCount": 5,
                            "createdAt": "2026-04-27T00:00:00Z",
                        }
                    }
                ]
            }
        }
    }
    monkeypatch.setattr(
        producthunt_server.httpx,
        "post",
        lambda *args, **kwargs: _Response(payload=payload),
    )

    out = json.loads(producthunt_server.search_product_hunt(query="agent", max_results=5))
    assert out[0]["title"] == "AgentKit"
    assert out[0]["source_layer"] == "工业层"
    assert out[0]["votes_count"] == 42


def test_producthunt_uses_client_credentials_when_secret_exists(monkeypatch) -> None:
    """API key plus secret are exchanged for a client-level access token."""
    monkeypatch.setenv("PRODUCTHUNT_API_KEY", "client-id")
    monkeypatch.setenv("PRODUCTHUNT_API_SECRET", "client-secret")
    calls: list[str] = []

    def fake_post(url: str, **kwargs) -> _Response:
        """Return token response first, GraphQL response second."""
        calls.append(url)
        if url == producthunt_server.PRODUCTHUNT_TOKEN_ENDPOINT:
            return _Response(payload={"access_token": "access-token"})
        assert kwargs["headers"]["Authorization"] == "Bearer access-token"
        return _Response(payload={"data": {"posts": {"edges": []}}})

    monkeypatch.setattr(producthunt_server.httpx, "post", fake_post)
    out = json.loads(producthunt_server.search_product_hunt(max_results=1))
    assert out == []
    assert calls == [
        producthunt_server.PRODUCTHUNT_TOKEN_ENDPOINT,
        producthunt_server.PRODUCTHUNT_ENDPOINT,
    ]


def test_reddit_normalizes_yars_results(monkeypatch) -> None:
    """Reddit results are normalized into community-layer crawled items."""

    class FakeYARS:
        """YARS double with the method used by search_reddit."""

        def __init__(self, timeout: int = 30) -> None:
            self.timeout = timeout

        def search_subreddit(self, subreddit: str, query: str, limit: int = 10) -> list[dict]:
            """Return one fake search result."""
            return [
                {
                    "title": "New local model",
                    "link": "https://www.reddit.com/r/LocalLLaMA/comments/1/demo",
                    "description": "Community feedback",
                }
            ]

    monkeypatch.setattr(reddit_server, "YARS", FakeYARS)
    out = json.loads(reddit_server.search_reddit("model", "LocalLLaMA", 3))
    assert out[0]["source_platform"] == "reddit"
    assert out[0]["source_layer"] == "社区层"
    assert out[0]["subreddit"] == "LocalLLaMA"


def test_reddit_wraps_yars_failures(monkeypatch) -> None:
    """YARS internal network errors are surfaced as tool-level failures."""

    class BrokenYARS:
        """YARS double that raises like the vendored library can under network failure."""

        def __init__(self, timeout: int = 30) -> None:
            self.timeout = timeout

        def search_subreddit(self, subreddit: str, query: str, limit: int = 10) -> list[dict]:
            """Raise a low-level error."""
            raise UnboundLocalError("response")

    monkeypatch.setattr(reddit_server, "YARS", BrokenYARS)
    try:
        reddit_server.search_reddit("model", "LocalLLaMA", 3)
    except RuntimeError as exc:
        assert "Reddit fetch failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_notion_query_uses_data_sources_when_available(monkeypatch) -> None:
    """Current notion-client exposes query under data_sources."""
    from ai_radar.mcp_servers import notion_server

    class FakeDataSources:
        """Minimal data_sources endpoint double."""

        def query(self, **kwargs) -> dict:
            """Return one fake page and capture data_source_id compatibility."""
            assert kwargs["data_source_id"] == "wiki-ds"
            return {"results": [{"id": "p1", "url": "u", "properties": {}}]}

    class FakeClient:
        """Minimal Notion client double."""

        def __init__(self) -> None:
            self.data_sources = FakeDataSources()
            self.databases = self

        def retrieve(self, database_id: str) -> dict:
            """Return a database with a child data source id."""
            assert database_id == "wiki-db"
            return {"data_sources": [{"id": "wiki-ds"}]}

    monkeypatch.setenv("NOTION_WIKI_DATABASE_ID", "wiki-db")
    monkeypatch.setattr(notion_server, "_client", lambda: FakeClient())
    out = json.loads(notion_server.query_notion_wiki(max_results=1))
    assert out == [{"page_id": "p1", "url": "u"}]


def test_individual_register_functions() -> None:
    """Register functions expose the expected tool names."""
    registry = ToolRegistry()
    fetch_page_server.register(registry)
    assert registry.names() == ["fetch_page"]
