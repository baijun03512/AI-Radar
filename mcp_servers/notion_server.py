"""Notion-backed wiki/raw/preferences tools."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from notion_client import Client

from ..runtime.tool_registry import Tool, ToolRegistry

SUSPICIOUS_TOKENS = (
    "锛",
    "鎻",
    "璇",
    "鍙",
    "鈥",
    "馃",
    "姝",
    "绯",
    "€",
    "�",
)
PREFERENCES_SNAPSHOT_TITLE = "AI Radar Preferences Snapshot"


def _client() -> Client:
    """Create a Notion client from environment variables."""
    token = os.getenv("NOTION_API_KEY")
    if not token:
        raise RuntimeError("NOTION_API_KEY is required")
    return Client(auth=token)


def _plain_text(prop: dict[str, Any]) -> str:
    """Extract plain text from a Notion title/rich_text property."""
    chunks = prop.get("title") or prop.get("rich_text") or []
    return "".join(chunk.get("plain_text", "") for chunk in chunks)


def _page_to_summary(page: dict[str, Any]) -> dict[str, Any]:
    """Flatten common Notion page properties into a compact summary."""
    props = page.get("properties", {})
    flattened: dict[str, Any] = {"page_id": page.get("id"), "url": page.get("url", "")}
    for key, value in props.items():
        prop_type = value.get("type")
        if prop_type in {"title", "rich_text"}:
            flattened[key] = _plain_text(value)
        elif prop_type == "multi_select":
            flattened[key] = [item.get("name", "") for item in value.get("multi_select", [])]
        elif prop_type == "select":
            flattened[key] = (value.get("select") or {}).get("name", "")
        elif prop_type == "number":
            flattened[key] = value.get("number")
        elif prop_type == "url":
            flattened[key] = value.get("url", "")
        elif prop_type == "date":
            flattened[key] = value.get("date")
    return flattened


def _normalize_notion_id(value: str) -> str:
    """Accept either a bare Notion id or a full shared URL."""
    text = (value or "").strip()
    if not text:
        return ""
    matched = re.search(r"([0-9a-fA-F]{32})", text)
    return matched.group(1) if matched else text


def _clean_text(text: str, *, fallback: str = "") -> str:
    """Normalize text before writing to Notion and avoid obvious mojibake."""
    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return fallback.strip()

    suspicious_hits = sum(token in cleaned for token in SUSPICIOUS_TOKENS)
    if "???" in cleaned or suspicious_hits >= 2:
        return fallback.strip() or "内容存在编码异常，建议从最新卡片或对话页重新生成摘要。"
    return cleaned


def _resolve_data_source_id(notion: Client, database_id: str) -> str:
    """Resolve a Notion database id to the first data source id when needed."""
    explicit = os.getenv("NOTION_WIKI_DATA_SOURCE_ID")
    if explicit:
        return explicit
    database = notion.databases.retrieve(database_id=database_id)
    data_sources = database.get("data_sources") or []
    if not data_sources:
        return database_id
    return str(data_sources[0].get("id") or database_id)


def _schema(notion: Client, database_id: str) -> tuple[str, dict[str, Any]]:
    """Return the active data source id plus its property schema."""
    data_source_id = _resolve_data_source_id(notion, database_id)
    if hasattr(notion, "data_sources") and hasattr(notion.data_sources, "retrieve"):
        data_source = notion.data_sources.retrieve(data_source_id=data_source_id)
        return data_source_id, data_source.get("properties", {})
    database = notion.databases.retrieve(database_id=database_id)
    return data_source_id, database.get("properties", {})


def _find_property_name(properties: dict[str, Any], prop_type: str, aliases: list[str]) -> str | None:
    """Find the first property matching a type, preferring alias names."""
    for alias in aliases:
        prop = properties.get(alias)
        if prop and prop.get("type") == prop_type:
            return alias
    for name, prop in properties.items():
        if prop.get("type") == prop_type:
            return name
    return None


def _list_children(notion: Client, block_id: str) -> list[dict[str, Any]]:
    """List child blocks under one page/block, following pagination."""
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        payload = notion.blocks.children.list(block_id=block_id, start_cursor=cursor) if cursor else notion.blocks.children.list(block_id=block_id)
        results.extend(payload.get("results", []))
        if not payload.get("has_more"):
            break
        cursor = payload.get("next_cursor")
    return results


def _rich_text_content(text: str) -> list[dict[str, Any]]:
    """Return a Notion rich_text payload."""
    return [{"type": "text", "text": {"content": text}}]


def _block_text(block: dict[str, Any]) -> str:
    """Extract visible text from a common Notion block."""
    block_type = block.get("type")
    payload = block.get(block_type or "", {})
    rich_text = payload.get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in rich_text)


def _preferences_root_page_id(page_id: str = "") -> str:
    """Resolve the configured preferences page id."""
    resolved = _normalize_notion_id(page_id or os.getenv("NOTION_PREFERENCES_PAGE_ID", ""))
    if not resolved:
        raise RuntimeError("NOTION_PREFERENCES_PAGE_ID is required")
    return resolved


def _ensure_preferences_snapshot_page(notion: Client, root_page_id: str) -> tuple[str, str]:
    """Create or reuse the dedicated child page that stores the mirrored profile."""
    for block in _list_children(notion, root_page_id):
        if block.get("type") == "child_page" and block.get("child_page", {}).get("title") == PREFERENCES_SNAPSHOT_TITLE:
            return str(block.get("id")), block.get("url", "")

    page = notion.pages.create(
        parent={"page_id": root_page_id},
        properties={"title": {"title": [{"text": {"content": PREFERENCES_SNAPSHOT_TITLE}}]}},
    )
    return str(page.get("id")), page.get("url", "")


def query_notion_wiki(query: str = "", max_results: int = 10) -> str:
    """Query the wiki database and return compact page summaries."""
    database_id = os.getenv("NOTION_WIKI_DATABASE_ID")
    if not database_id:
        raise RuntimeError("NOTION_WIKI_DATABASE_ID is required")

    notion = _client()
    data_source_id, properties = _schema(notion, database_id)
    title_prop = _find_property_name(properties, "title", ["name", "Name", "名称", "title", "Title"])
    tags_multi_prop = _find_property_name(properties, "multi_select", ["tags", "Tags", "标签"])
    tags_text_prop = _find_property_name(properties, "rich_text", ["tags", "Tags", "标签"])

    kwargs: dict[str, Any] = {"page_size": max_results}
    if query:
        filters: list[dict[str, Any]] = []
        if title_prop:
            filters.append({"property": title_prop, "title": {"contains": query}})
        if tags_multi_prop:
            filters.append({"property": tags_multi_prop, "multi_select": {"contains": query}})
        if tags_text_prop:
            filters.append({"property": tags_text_prop, "rich_text": {"contains": query}})
        if filters:
            kwargs["filter"] = {"or": filters} if len(filters) > 1 else filters[0]

    if hasattr(notion, "data_sources"):
        kwargs["data_source_id"] = data_source_id
        result = notion.data_sources.query(**kwargs)
    else:
        kwargs["database_id"] = database_id
        result = notion.databases.query(**kwargs)

    pages = [_page_to_summary(page) for page in result.get("results", [])]
    return json.dumps(pages, ensure_ascii=False)


def create_notion_raw(
    title: str,
    source_url: str,
    content: str,
    source_platform: str = "",
) -> str:
    """Create one raw-source page in the configured Notion raw database."""
    database_id = os.getenv("NOTION_RAW_DATABASE_ID")
    if not database_id:
        raise RuntimeError("NOTION_RAW_DATABASE_ID is required")

    notion = _client()
    data_source_id, properties = _schema(notion, database_id)
    title_prop = _find_property_name(properties, "title", ["title", "Title", "名称", "name", "Name"])
    url_prop = _find_property_name(properties, "url", ["source_url", "Source URL", "链接", "url", "URL"])
    platform_prop = _find_property_name(properties, "rich_text", ["source_platform", "Source Platform", "平台"])
    date_prop = _find_property_name(properties, "date", ["fetched_at", "Fetched At", "抓取时间"])

    notion_properties: dict[str, Any] = {}
    if title_prop:
        notion_properties[title_prop] = {"title": [{"text": {"content": _clean_text(title, fallback="Untitled")[:200]}}]}
    if url_prop and source_url:
        notion_properties[url_prop] = {"url": source_url}
    if platform_prop and source_platform:
        notion_properties[platform_prop] = {"rich_text": [{"text": {"content": _clean_text(source_platform)[:1800]}}]}
    if date_prop:
        notion_properties[date_prop] = {"date": {"start": datetime.now(timezone.utc).isoformat()}}

    payload: dict[str, Any] = {
        "parent": {"data_source_id": data_source_id} if hasattr(notion, "data_sources") else {"database_id": database_id},
        "properties": notion_properties,
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": _clean_text(content, fallback=title)[:1800]}}]
                },
            }
        ],
    }
    page = notion.pages.create(**payload)
    return json.dumps({"page_id": page.get("id"), "url": page.get("url")}, ensure_ascii=False)


def upsert_notion_wiki(name: str, one_liner: str, tags: list[str] | None = None) -> str:
    """Create a minimal wiki page using the available schema."""
    database_id = os.getenv("NOTION_WIKI_DATABASE_ID")
    if not database_id:
        raise RuntimeError("NOTION_WIKI_DATABASE_ID is required")

    notion = _client()
    data_source_id, properties = _schema(notion, database_id)
    title_prop = _find_property_name(properties, "title", ["name", "Name", "名称", "title", "Title"])
    rich_text_prop = _find_property_name(properties, "rich_text", ["one_liner", "One Liner", "摘要", "简介"])
    tags_multi_prop = _find_property_name(properties, "multi_select", ["tags", "Tags", "标签"])
    tags_text_prop = _find_property_name(properties, "rich_text", ["tags", "Tags", "标签"])
    date_prop = _find_property_name(properties, "date", ["last_updated", "Last Updated", "更新时间"])

    safe_name = _clean_text(name, fallback="Untitled")[:200]
    safe_summary = _clean_text(one_liner, fallback=f"{safe_name} 已保存，建议在对话页查看最新中文总结。")[:1800]
    safe_tags = [_clean_text(tag) for tag in (tags or [])]
    safe_tags = [tag for tag in safe_tags if tag and "内容存在编码异常" not in tag][:10]

    notion_properties: dict[str, Any] = {}
    if title_prop:
        notion_properties[title_prop] = {"title": [{"text": {"content": safe_name}}]}
    if rich_text_prop:
        notion_properties[rich_text_prop] = {"rich_text": [{"text": {"content": safe_summary}}]}
    if tags_multi_prop and safe_tags:
        notion_properties[tags_multi_prop] = {"multi_select": [{"name": tag} for tag in safe_tags]}
    elif tags_text_prop and safe_tags and tags_text_prop != rich_text_prop:
        notion_properties[tags_text_prop] = {"rich_text": [{"text": {"content": ", ".join(safe_tags)[:1800]}}]}
    if date_prop:
        notion_properties[date_prop] = {"date": {"start": datetime.now(timezone.utc).isoformat()}}

    children: list[dict[str, Any]] = []
    if not rich_text_prop:
        body = safe_summary
        if safe_tags:
            body = f"{body}\n\n标签: {', '.join(safe_tags)}"
        children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": body[:1800]}}]},
            }
        )

    payload: dict[str, Any] = {
        "parent": {"data_source_id": data_source_id} if hasattr(notion, "data_sources") else {"database_id": database_id},
        "properties": notion_properties,
    }
    if children:
        payload["children"] = children

    page = notion.pages.create(**payload)
    return json.dumps({"page_id": page.get("id"), "url": page.get("url")}, ensure_ascii=False)


def load_notion_preferences(page_id: str = "") -> str:
    """Load the mirrored preferences JSON from the configured Notion page."""
    notion = _client()
    root_page_id = _preferences_root_page_id(page_id)
    snapshot_page_id, _ = _ensure_preferences_snapshot_page(notion, root_page_id)
    blocks = _list_children(notion, snapshot_page_id)
    for block in blocks:
        if block.get("type") == "code":
            text = _block_text(block).strip()
            if text:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue
                return json.dumps(data, ensure_ascii=False)
    return json.dumps({})


def sync_notion_preferences(profile: dict[str, Any], page_id: str = "") -> str:
    """Mirror the current local preferences profile into the configured Notion page."""
    notion = _client()
    root_page_id = _preferences_root_page_id(page_id)
    snapshot_page_id, snapshot_url = _ensure_preferences_snapshot_page(notion, root_page_id)

    for block in _list_children(notion, snapshot_page_id):
        notion.blocks.delete(block_id=block["id"])

    clean_profile = json.loads(json.dumps(profile, ensure_ascii=False))
    profile_json = json.dumps(clean_profile, ensure_ascii=False, indent=2)
    summary = (
        f"interests={', '.join(clean_profile.get('interests', [])[:3])} | "
        f"platforms={', '.join(clean_profile.get('preferred_platforms', [])[:3])} | "
        f"exploration_ratio={clean_profile.get('exploration_ratio', 0.3)} | "
        f"feed_size={clean_profile.get('feed_size', 10)}"
    )

    notion.blocks.children.append(
        block_id=snapshot_page_id,
        children=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text_content(PREFERENCES_SNAPSHOT_TITLE)},
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": _rich_text_content(
                        f"Updated at: {datetime.now(timezone.utc).isoformat()}"
                    )
                },
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text_content(summary[:1800])},
            },
            {
                "object": "block",
                "type": "code",
                "code": {
                    "language": "json",
                    "rich_text": _rich_text_content(profile_json[:1800]),
                },
            },
        ],
    )
    return json.dumps({"page_id": snapshot_page_id, "url": snapshot_url}, ensure_ascii=False)


def register(registry: ToolRegistry) -> None:
    """Register Notion read/write tools."""
    registry.register(
        Tool(
            name="query_notion_wiki",
            description="Query Notion wiki pages and return compact summaries.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                    "max_results": {"type": "integer", "default": 10},
                },
            },
            handler=query_notion_wiki,
        )
    )
    registry.register(
        Tool(
            name="create_notion_raw",
            description="Write raw crawled content to the Notion raw database.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "source_url": {"type": "string"},
                    "content": {"type": "string"},
                    "source_platform": {"type": "string", "default": ""},
                },
                "required": ["title", "source_url", "content"],
            },
            handler=create_notion_raw,
        )
    )
    registry.register(
        Tool(
            name="upsert_notion_wiki",
            description="Create a minimal Notion wiki page for an AI product/tool.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "one_liner": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "one_liner"],
            },
            handler=upsert_notion_wiki,
        )
    )
    registry.register(
        Tool(
            name="load_notion_preferences",
            description="Load the mirrored preferences profile from a Notion page.",
            input_schema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "default": ""},
                },
            },
            handler=load_notion_preferences,
        )
    )
    registry.register(
        Tool(
            name="sync_notion_preferences",
            description="Mirror the local preferences profile into a Notion page.",
            input_schema={
                "type": "object",
                "properties": {
                    "profile": {"type": "object"},
                    "page_id": {"type": "string", "default": ""},
                },
                "required": ["profile"],
            },
            handler=sync_notion_preferences,
        )
    )
