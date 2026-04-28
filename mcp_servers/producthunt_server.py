"""Product Hunt GraphQL top-products tool."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from typing import Any

import httpx

from ..runtime.tool_registry import Tool, ToolRegistry

PRODUCTHUNT_ENDPOINT = "https://api.producthunt.com/v2/api/graphql"
PRODUCTHUNT_TOKEN_ENDPOINT = "https://api.producthunt.com/v2/oauth/token"
DEFAULT_TIMEOUT = 30.0


def _normalize_post(node: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    """Convert a Product Hunt post node into the CrawledItem-like contract."""
    product_url = node.get("url") or node.get("website") or ""
    tagline = node.get("tagline") or ""
    description = node.get("description") or ""
    summary = (tagline or description or "").strip()
    return {
        "item_id": str(node.get("id") or node.get("slug") or product_url),
        "title": (node.get("name") or "").strip(),
        "summary": summary[:500],
        "source_platform": "product_hunt",
        "source_layer": "工业层",
        "source_url": product_url,
        "published_at": node.get("createdAt") or "",
        "fetched_at": fetched_at,
        "votes_count": node.get("votesCount", 0),
        "comments_count": node.get("commentsCount", 0),
        "slug": node.get("slug", ""),
    }


def _access_token() -> str:
    """Return a Product Hunt access token from env or client credentials."""
    developer_token = os.getenv("PRODUCTHUNT_DEVELOPER_TOKEN")
    if developer_token:
        return developer_token

    client_id = os.getenv("PRODUCTHUNT_API_KEY")
    client_secret = os.getenv("PRODUCTHUNT_API_SECRET")
    if not client_id:
        raise RuntimeError("PRODUCTHUNT_API_KEY or PRODUCTHUNT_DEVELOPER_TOKEN is required")
    if not client_secret:
        return client_id

    resp = httpx.post(
        PRODUCTHUNT_TOKEN_ENDPOINT,
        json={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        return client_id
    return str(token)


def search_product_hunt(
    query: str = "",
    max_results: int = 10,
    posted_after: str | None = None,
) -> str:
    """Return recent Product Hunt posts, optionally filtered by a text query."""
    token = _access_token()
    after = posted_after or f"{date.today().isoformat()}T00:00:00Z"
    gql = """
    query SearchProductHunt($first: Int!, $postedAfter: DateTime) {
      posts(first: $first, postedAfter: $postedAfter, order: VOTES) {
        edges {
          node {
            id
            name
            tagline
            description
            url
            website
            slug
            votesCount
            commentsCount
            createdAt
          }
        }
      }
    }
    """
    headers = {"Authorization": f"Bearer {token}"}
    variables = {"first": max(max_results * 2, max_results), "postedAfter": after}
    resp = httpx.post(
        PRODUCTHUNT_ENDPOINT,
        json={"query": gql, "variables": variables},
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(json.dumps(body["errors"], ensure_ascii=False))

    fetched_at = datetime.now(timezone.utc).isoformat()
    edges = body.get("data", {}).get("posts", {}).get("edges", [])
    items = [_normalize_post(edge.get("node", {}), fetched_at) for edge in edges]
    if query:
        needle = query.lower()
        items = [
            item
            for item in items
            if needle in item["title"].lower() or needle in item["summary"].lower()
        ]
    return json.dumps(items[:max_results], ensure_ascii=False)


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Optional keyword filter after fetching top posts.",
            "default": "",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum products to return.",
            "default": 10,
        },
        "posted_after": {
            "type": "string",
            "description": "ISO datetime lower bound; defaults to today 00:00 UTC.",
        },
    },
}


def register(registry: ToolRegistry) -> None:
    """Register the Product Hunt tool."""
    registry.register(
        Tool(
            name="search_product_hunt",
            description="Fetch Product Hunt top posts and return CrawledItem objects.",
            input_schema=_INPUT_SCHEMA,
            handler=search_product_hunt,
        )
    )
