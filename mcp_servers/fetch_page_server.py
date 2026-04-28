"""Generic web page fetcher for product pages, docs, and blog posts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from ..runtime.tool_registry import Tool, ToolRegistry

DEFAULT_TIMEOUT = 30.0
MAX_TEXT_CHARS = 8000


def _clean_text(text: str) -> str:
    """Normalize whitespace while preserving readable text."""
    return " ".join(text.split())


def fetch_page(url: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    """Fetch a URL and return title, metadata, and readable page text as JSON."""
    headers = {
        "User-Agent": (
            "AIProductRadar/0.1 (+https://example.local; "
            "research crawler for personal use)"
        )
    }
    resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = _clean_text(soup.title.get_text(" ")) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = ""
    if description_tag and description_tag.get("content"):
        description = _clean_text(str(description_tag["content"]))

    text = _clean_text(soup.get_text(" "))
    payload: dict[str, Any] = {
        "url": str(resp.url),
        "title": title,
        "description": description,
        "content": text[:max_chars],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status_code": resp.status_code,
    }
    return json.dumps(payload, ensure_ascii=False)


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "Page URL to fetch."},
        "max_chars": {
            "type": "integer",
            "description": "Maximum cleaned text characters to return.",
            "default": MAX_TEXT_CHARS,
        },
    },
    "required": ["url"],
}


def register(registry: ToolRegistry) -> None:
    """Register the fetch_page tool."""
    registry.register(
        Tool(
            name="fetch_page",
            description="Fetch a web page and extract readable title, metadata, and text.",
            input_schema=_INPUT_SCHEMA,
            handler=fetch_page,
        )
    )
