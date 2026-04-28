"""Chat agent with intent detection and multi-source retrieval."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from ..runtime.tool_registry import ToolRegistry
from ..schemas.contracts import ChatToMemoryPayload, ChatTurn, SourceUsed

IntentType = Literal["exploratory", "deep_dive", "comparison"]

LAYER_ALIASES = {
    "academic": "academic",
    "industry": "industry",
    "community": "community",
    "学术层": "academic",
    "工业层": "industry",
    "社区层": "community",
    "瀛︽湳灞?": "academic",
    "宸ヤ笟灞?": "industry",
    "绀惧尯灞?": "community",
}

LAYER_LABELS = {
    "academic": "学术层",
    "industry": "工业层",
    "community": "社区层",
}


@dataclass
class RetrievedSource:
    """One raw retrieval result used during synthesis."""

    layer: str
    platform: str
    url: str
    title: str
    snippet: str


@dataclass
class ChatAgentResult:
    """Structured result of one chat turn."""

    intent_type: IntentType
    answer: str
    sources_used: list[SourceUsed] = field(default_factory=list)
    retrievals: list[RetrievedSource] = field(default_factory=list)
    new_insights: str = ""


class ChatAgent:
    """Handle exploratory, deep-dive, and comparison style questions."""

    TOOL_SEQUENCE = (
        ("query_notion_wiki", "industry"),
        ("search_product_hunt", "industry"),
        ("search_arxiv", "academic"),
        ("search_reddit", "community"),
    )

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def detect_intent(self, query: str) -> IntentType:
        """Classify the user query into one of three supported intents."""
        text = query.lower()
        if " vs " in text or "compare" in text or "区别" in query or "对比" in query:
            return "comparison"
        if any(token in text for token in ("how", "why", "architecture", "deep", "details")):
            return "deep_dive"
        if any(token in query for token in ("原理", "深入", "细节", "技术")):
            return "deep_dive"
        return "exploratory"

    def answer_query(self, query: str, *, product_name: str = "", max_per_tool: int = 2) -> ChatAgentResult:
        """Retrieve relevant sources and synthesize a grounded answer."""
        intent = self.detect_intent(query)
        topics = self._extract_topics(query, intent, product_name=product_name)
        retrievals: list[RetrievedSource] = []
        for topic in topics:
            retrievals.extend(self._retrieve_topic(topic, intent=intent, max_per_tool=max_per_tool))

        sources_used = [
            SourceUsed(layer=item.layer, url=item.url, snippet=item.snippet[:240])
            for item in retrievals[:6]
        ]
        answer = self._synthesize_answer(query, intent, topics, retrievals)
        new_insights = self._new_insights(intent, retrievals)
        return ChatAgentResult(
            intent_type=intent,
            answer=answer,
            sources_used=sources_used,
            retrievals=retrievals,
            new_insights=new_insights,
        )

    def build_memory_payload(
        self,
        *,
        product_id: str,
        product_name: str,
        query: str,
        result: ChatAgentResult,
    ) -> ChatToMemoryPayload:
        """Convert one chat answer into the memory handoff payload."""
        conversation = [
            ChatTurn(role="user", content=query),
            ChatTurn(role="assistant", content=result.answer),
        ]
        return ChatToMemoryPayload(
            product_id=product_id,
            product_name=product_name,
            conversation=conversation,
            intent_type=result.intent_type,
            sources_used=result.sources_used,
            new_insights=result.new_insights,
            ended_at=datetime.now(timezone.utc).isoformat(),
            end_reason="manual_save",
        )

    def _extract_topics(self, query: str, intent: IntentType, *, product_name: str = "") -> list[str]:
        """Extract one or more topics from the user query."""
        if intent == "comparison":
            lowered = re.sub(r"\b(compare|comparison|vs\.?|versus)\b", "|", query, flags=re.IGNORECASE)
            parts = [
                part.strip(" ?，,")
                for part in re.split(r"[|/]|对比|和", lowered)
                if part.strip(" ?，,")
            ]
            return parts[:2] if len(parts) >= 2 else [query]

        stripped = query.strip()
        if not product_name:
            return [stripped]

        generic_queries = {
            "给我简单介绍一下",
            "简单介绍一下",
            "介绍一下",
            "说说这个",
            "这个是什么",
            "what is this",
            "tell me about this",
            "give me a quick intro",
        }
        if stripped.lower() in generic_queries or len(stripped) <= 12:
            return [product_name]
        return [f"{product_name} {stripped}".strip()]

    def _retrieve_topic(
        self,
        topic: str,
        *,
        intent: IntentType,
        max_per_tool: int,
    ) -> list[RetrievedSource]:
        """Retrieve relevant sources for one topic across available tools."""
        retrievals: list[RetrievedSource] = []
        for tool_name, fallback_layer in self.TOOL_SEQUENCE:
            if tool_name not in self.registry.names():
                continue
            tool_input = self._tool_input(tool_name, topic, intent, max_per_tool)
            try:
                raw = self.registry.execute(tool_name, tool_input)
            except Exception:
                continue
            parsed = self._parse_tool_output(tool_name, raw, fallback_layer)
            retrievals.extend(parsed[:max_per_tool])
        return retrievals

    def _tool_input(
        self,
        tool_name: str,
        topic: str,
        intent: IntentType,
        max_per_tool: int,
    ) -> dict[str, Any]:
        """Build a per-tool input payload for the retrieval step."""
        if tool_name == "query_notion_wiki":
            return {"query": topic, "max_results": max_per_tool}
        if tool_name == "search_reddit":
            subreddit = "LocalLLaMA" if intent == "deep_dive" else "MachineLearning"
            return {"query": topic, "subreddit": subreddit, "max_results": max_per_tool}
        if tool_name == "search_arxiv":
            return {"query": topic, "max_results": max_per_tool, "days": 90}
        return {"query": topic, "max_results": max_per_tool}

    def _parse_tool_output(
        self,
        tool_name: str,
        raw: Any,
        fallback_layer: str,
    ) -> list[RetrievedSource]:
        """Normalize tool JSON output into RetrievedSource records."""
        data = json.loads(raw) if isinstance(raw, str) else raw
        records: list[RetrievedSource] = []
        for row in data:
            layer = self._infer_layer(tool_name, row, fallback_layer)
            url = row.get("source_url") or row.get("url", "")
            title = row.get("title") or row.get("name", "")
            snippet = row.get("summary") or row.get("one_liner") or row.get("tags") or ""
            records.append(
                RetrievedSource(
                    layer=layer,
                    platform=row.get("source_platform", tool_name.replace("search_", "")),
                    url=url,
                    title=title,
                    snippet=str(snippet),
                )
            )
        return records

    def _infer_layer(self, tool_name: str, row: dict[str, Any], fallback_layer: str) -> str:
        """Infer a stable source layer from a tool result row."""
        explicit = self._normalize_layer(row.get("source_layer"))
        if explicit is not None:
            return explicit
        if tool_name == "query_notion_wiki":
            for tag in row.get("tags") or []:
                normalized = self._normalize_layer(tag)
                if normalized is not None:
                    return normalized
        return fallback_layer

    def _normalize_layer(self, value: Any) -> str | None:
        """Normalize legacy or localized source-layer values."""
        if not value:
            return None
        text = str(value).strip()
        normalized = LAYER_ALIASES.get(text)
        if normalized is not None:
            return normalized
        lowered = text.lower()
        if "academic" in lowered or "学术" in text:
            return "academic"
        if "industry" in lowered or "工业" in text:
            return "industry"
        if "community" in lowered or "社区" in text:
            return "community"
        return None

    def _synthesize_answer(
        self,
        query: str,
        intent: IntentType,
        topics: list[str],
        retrievals: list[RetrievedSource],
    ) -> str:
        """Turn retrieved sources into a concise user-facing answer."""
        if not retrievals:
            return f"我暂时还没有检索到和“{query}”直接相关、且能交叉验证的多源信息。"

        by_layer: dict[str, list[RetrievedSource]] = {}
        for source in retrievals:
            by_layer.setdefault(source.layer, []).append(source)

        if intent == "comparison" and len(topics) >= 2:
            left, right = topics[0], topics[1]
            layer_notes = []
            for layer in ("academic", "industry", "community"):
                if layer in by_layer:
                    layer_notes.append(f"{LAYER_LABELS[layer]}: {by_layer[layer][0].title}")
            return (
                f"如果把 {left} 和 {right} 放在一起看，当前信号已经覆盖多个层级。"
                f"{'；'.join(layer_notes[:3])}。"
                f"学术层更偏方法和评测，工业层更偏产品化落地，社区层更偏真实使用反馈。"
            )

        highlights = []
        for layer in ("academic", "industry", "community"):
            if layer in by_layer:
                highlights.append(f"{LAYER_LABELS[layer]}: {by_layer[layer][0].title}")
        prefix = "深入看，这个话题最值得抓住的线索是" if intent == "deep_dive" else "当前最清晰的信号是"
        return f"{prefix}：{'；'.join(highlights)}。"

    def _new_insights(self, intent: IntentType, retrievals: list[RetrievedSource]) -> str:
        """Generate a concise memory-friendly insight summary."""
        unique_layers = sorted({LAYER_LABELS.get(item.layer, item.layer) for item in retrievals})
        return (
            f"{intent} 问题共整合了 {len(retrievals)} 条检索结果，覆盖 {', '.join(unique_layers)}。"
        )
