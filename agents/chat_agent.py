"""Chat agent with grounded retrieval and optional LLM synthesis."""
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
    """Handle exploratory, deep-dive, and comparison questions around one feed card."""

    TOOL_SEQUENCE = (
        ("query_notion_wiki", "industry"),
        ("search_product_hunt", "industry"),
        ("search_arxiv", "academic"),
        ("search_reddit", "community"),
    )

    def __init__(self, registry: ToolRegistry, llm_client: Any | None = None) -> None:
        self.registry = registry
        self._llm = llm_client

    def detect_intent(self, query: str) -> IntentType:
        """Classify the user query into one of three supported intents."""
        lowered = query.lower()
        if " vs " in lowered or "compare" in lowered or "区别" in query or "对比" in query:
            return "comparison"
        if any(token in lowered for token in ("how", "why", "architecture", "deep", "details")):
            return "deep_dive"
        if any(token in query for token in ("原理", "深入", "细节", "技术", "怎么做", "为什么")):
            return "deep_dive"
        return "exploratory"

    def answer_query(
        self,
        query: str,
        *,
        product_name: str = "",
        product_context: str = "",
        max_per_tool: int = 2,
    ) -> ChatAgentResult:
        """Retrieve relevant sources and synthesize a grounded answer."""
        intent = self.detect_intent(query)
        topics = self._extract_topics(query, intent, product_name=product_name)
        retrievals: list[RetrievedSource] = []
        for topic in topics:
            retrievals.extend(self._retrieve_topic(topic, intent=intent, max_per_tool=max_per_tool))

        relevant = self._select_relevant_retrievals(
            retrievals,
            product_name=product_name,
            product_context=product_context,
            query=query,
            limit=6,
        )
        sources_used = [
            SourceUsed(layer=item.layer, url=item.url, snippet=item.snippet[:240])
            for item in relevant
        ]
        answer = self._llm_answer(
            query=query,
            intent=intent,
            retrievals=relevant,
            product_name=product_name,
            product_context=product_context,
        )
        if not answer:
            answer = self._fallback_answer(
                query=query,
                intent=intent,
                topics=topics,
                retrievals=relevant,
                product_name=product_name,
                product_context=product_context,
            )
        new_insights = self._new_insights(intent, relevant, product_name=product_name)
        return ChatAgentResult(
            intent_type=intent,
            answer=answer,
            sources_used=sources_used,
            retrievals=relevant,
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

    def _llm_answer(
        self,
        *,
        query: str,
        intent: IntentType,
        retrievals: list[RetrievedSource],
        product_name: str,
        product_context: str,
    ) -> str:
        """Ask the LLM to answer from current card context plus aligned sources."""
        if self._llm is None:
            return ""

        evidence = [
            {
                "layer": LAYER_LABELS.get(item.layer, item.layer),
                "platform": item.platform,
                "title": item.title,
                "snippet": item.snippet[:320],
                "url": item.url,
            }
            for item in retrievals[:4]
        ]
        try:
            response = self._llm.call(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "请围绕用户当前点开的卡片回答问题。\n\n"
                            f"卡片标题：{product_name}\n"
                            f"卡片摘要：{product_context}\n"
                            f"用户问题：{query}\n"
                            f"意图：{intent}\n\n"
                            "下面这些是已经筛过、和当前卡片尽量对齐的证据。只能使用这些证据和卡片本身，不要编造：\n"
                            + json.dumps(evidence, ensure_ascii=False, indent=2)
                            + "\n\n要求：\n"
                            "1. 直接用简体中文回答。\n"
                            "2. 先解释当前卡片本身在讲什么，再补充证据。\n"
                            "3. 如果证据不够，就明确说不确定，不要串到别的产品或论文。\n"
                            "4. 120-260 字。\n"
                            "5. 不要写'根据资料'、'从信号看'这种空话。"
                        ),
                    }
                ],
                system=(
                    "你是 AI 产品雷达的中文分析助手。"
                    "你只回答当前卡片，不要因为关键词相近就把别的主体混进来。"
                ),
                max_tokens=420,
            )
        except Exception:
            return ""
        return response.text.strip()

    def _extract_topics(self, query: str, intent: IntentType, *, product_name: str = "") -> list[str]:
        """Extract retrieval topics from the user query."""
        if intent == "comparison":
            lowered = re.sub(r"\b(compare|comparison|vs\.?|versus)\b", "|", query, flags=re.IGNORECASE)
            parts = [
                part.strip(" ?，,")
                for part in re.split(r"[|/]|对比|和", lowered)
                if part.strip(" ?，,")
            ]
            return parts[:2] if len(parts) >= 2 else [query.strip()]

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
            retrievals.extend(self._parse_tool_output(tool_name, raw, fallback_layer)[:max_per_tool])
        return retrievals

    def _tool_input(
        self,
        tool_name: str,
        topic: str,
        intent: IntentType,
        max_per_tool: int,
    ) -> dict[str, Any]:
        """Build a per-tool input payload for retrieval."""
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
        if text in LAYER_ALIASES:
            return LAYER_ALIASES[text]
        lowered = text.lower()
        if "academic" in lowered or "学术" in text:
            return "academic"
        if "industry" in lowered or "工业" in text:
            return "industry"
        if "community" in lowered or "社区" in text:
            return "community"
        return None

    def _select_relevant_retrievals(
        self,
        retrievals: list[RetrievedSource],
        *,
        product_name: str,
        product_context: str,
        query: str,
        limit: int,
    ) -> list[RetrievedSource]:
        """Keep only retrievals that are genuinely about the current card."""
        if not retrievals:
            return []

        anchor_tokens = self._topic_tokens(" ".join([product_name, product_context, query]))
        product_tokens = self._topic_tokens(product_name)
        normalized_product = self._normalize_text(product_name)

        scored: list[tuple[float, RetrievedSource]] = []
        for item in retrievals:
            title_haystack = self._normalize_text(item.title)
            haystack = self._normalize_text(f"{item.title} {item.snippet}")
            item_tokens = set(haystack.split())
            title_tokens = set(title_haystack.split())
            overlap = len(anchor_tokens & item_tokens)
            product_overlap = len(product_tokens & title_tokens)
            exact_hit = 1.0 if normalized_product and normalized_product in title_haystack else 0.0
            acronym_hit = 0.7 if self._matches_acronym(product_name, title_haystack) else 0.0
            score = overlap + exact_hit + acronym_hit
            if product_name:
                anchored = exact_hit > 0 or acronym_hit > 0 or product_overlap >= 2
                if not anchored or score < 1.0:
                    continue
            elif score < 1.0:
                continue
            scored.append((score, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)

        unique: list[RetrievedSource] = []
        seen: set[tuple[str, str]] = set()
        for _, item in scored:
            key = (item.title, item.url)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
            if len(unique) >= limit:
                break
        return unique

    def _fallback_answer(
        self,
        *,
        query: str,
        intent: IntentType,
        topics: list[str],
        retrievals: list[RetrievedSource],
        product_name: str,
        product_context: str,
    ) -> str:
        """Fallback answer when the LLM is unavailable."""
        del query, intent
        if not retrievals:
            if product_context.strip():
                return (
                    f"这张卡现在说的是 {product_name}。\n"
                    f"从当前卡片本身看，{product_context.strip()}\n"
                    "不过这次外部检索没有找到足够对齐的补充材料，所以我先不拿无关结果硬拼。"
                )
            return (
                f"这张卡的主体是 {product_name or topics[0]}，"
                "但我这次没有命中足够对齐的外部材料，所以先不编造成熟判断。"
            )

        by_layer: dict[str, list[RetrievedSource]] = {}
        for source in retrievals:
            by_layer.setdefault(source.layer, []).append(source)

        lines: list[str] = []
        if product_context.strip():
            lines.append(f"先对齐当前卡片：{product_context.strip()}")
        else:
            lines.append(f"先对齐主体：这张卡讨论的是 {product_name or topics[0]}。")
        lines.append("围绕这张卡，当前最贴边的外部信号是：")
        for layer in ("academic", "industry", "community"):
            if layer in by_layer:
                lines.append(f"- {LAYER_LABELS[layer]}：{by_layer[layer][0].title}")
        if "community" in by_layer:
            lines.append("社区层更多是在补真实使用反馈和落地摩擦，不适合单独当结论。")
        return "\n".join(lines)

    def _new_insights(
        self,
        intent: IntentType,
        retrievals: list[RetrievedSource],
        *,
        product_name: str,
    ) -> str:
        """Generate a concise memory-friendly insight summary."""
        if not retrievals:
            return f"{product_name or '当前卡片'} 这轮对话没有命中足够对齐的外部证据，后续需要补更精准检索。"
        unique_layers = sorted({LAYER_LABELS.get(item.layer, item.layer) for item in retrievals})
        return (
            f"{product_name or '当前卡片'} 这轮 {intent} 对话最终保留了 {len(retrievals)} 条对齐证据，"
            f"覆盖 {', '.join(unique_layers)}。"
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize mixed-language titles into a whitespace token string."""
        cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
        return " ".join(cleaned.split())

    def _topic_tokens(self, text: str) -> set[str]:
        """Extract stable topical tokens for retrieval relevance checks."""
        stopwords = {
            "about",
            "after",
            "and",
            "commerce",
            "details",
            "does",
            "from",
            "give",
            "how",
            "into",
            "intro",
            "mapping",
            "on",
            "premise",
            "product",
            "quick",
            "tell",
            "that",
            "the",
            "this",
            "what",
            "why",
            "with",
        }
        return {
            token
            for token in self._normalize_text(text).split()
            if len(token) >= 3 and token not in stopwords
        }

    @staticmethod
    def _matches_acronym(product_name: str, haystack: str) -> bool:
        """Check whether the product acronym appears in the retrieved title."""
        acronym = "".join(ch for ch in product_name if ch.isupper() or ch.isdigit()).lower()
        if len(acronym) < 3:
            return False
        return acronym in haystack.replace(" ", "")
