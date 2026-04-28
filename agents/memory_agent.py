"""Memory agent for compiling chat traces into wiki-ready records."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..runtime.tool_registry import ToolRegistry
from ..schemas.contracts import ChatToMemoryPayload, ChatTurn, SourceUsed, WikiPage

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


@dataclass
class MemoryProcessResult:
    """Result of processing one chat payload into memory artifacts."""

    wiki_page: WikiPage
    quality_score: float
    notion_written: bool
    queued_for_retry: bool


class MemoryAgent:
    """Compile, quality-check, cache, and optionally persist wiki memory."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else Path("data/memory")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = self.base_dir / "sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.base_dir / "pending_writes.json"
        self.wiki_cache_path = self.base_dir / "wiki_cache.json"
        self.lock_path = self.base_dir / "memory.lock"

    def should_persist(
        self,
        *,
        session_closed: bool = False,
        manual_save: bool = False,
        idle_minutes: int = 0,
    ) -> bool:
        """Return whether a chat session has crossed a persistence boundary."""
        return manual_save or session_closed or idle_minutes >= 15

    def warm_wiki_cache(
        self,
        registry: ToolRegistry,
        *,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Load wiki summaries from Notion and store them locally."""
        if "query_notion_wiki" not in registry.names():
            return []
        raw = registry.execute("query_notion_wiki", {"query": "", "max_results": max_results})
        data = json.loads(raw) if isinstance(raw, str) else raw
        self.wiki_cache_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return data

    @staticmethod
    def _payload_from_dict(data: dict) -> ChatToMemoryPayload:
        """Reconstruct a ChatToMemoryPayload from a plain JSON dict."""
        data["conversation"] = [ChatTurn(**t) for t in data.get("conversation", [])]
        data["sources_used"] = [SourceUsed(**s) for s in data.get("sources_used", [])]
        return ChatToMemoryPayload(**data)

    def merge_payload(self, payload: ChatToMemoryPayload) -> ChatToMemoryPayload:
        """Merge a payload into the rolling session file for the product."""
        path = self.session_dir / f"{payload.product_id}.json"
        if path.exists():
            current = self._payload_from_dict(json.loads(path.read_text(encoding="utf-8")))
            current.conversation.extend(payload.conversation)
            current.sources_used.extend(payload.sources_used)
            current.new_insights = payload.new_insights
            current.ended_at = payload.ended_at
            current.end_reason = payload.end_reason
            merged = current
        else:
            merged = payload
        path.write_text(json.dumps(asdict(merged), ensure_ascii=False, indent=2), encoding="utf-8")
        return merged

    def compile_wiki_page(self, payload: ChatToMemoryPayload) -> WikiPage:
        """Compile one merged chat payload into a wiki-ready page."""
        normalized_sources = [
            (self._normalize_layer(source.layer), source.snippet)
            for source in payload.sources_used
        ]
        tags = sorted({layer for layer, _ in normalized_sources if layer is not None})
        notes = "\n".join(
            turn.content for turn in payload.conversation if turn.role == "assistant"
        )[:1800]
        by_layer = {layer: snippet for layer, snippet in normalized_sources if layer is not None}
        return WikiPage(
            name=payload.product_name,
            one_liner=payload.new_insights[:200],
            tags=tags or [payload.intent_type],
            source_layer=tags[0] if tags else "community",
            tech_principle=by_layer.get("academic", ""),
            product_impl=by_layer.get("industry", ""),
            user_feedback=by_layer.get("community", ""),
            chat_notes=notes,
            created_at=payload.ended_at,
            last_updated=payload.ended_at,
        )

    def quality_check(self, wiki_page: WikiPage) -> float:
        """Score the compiled wiki page on a simple 1-5 heuristic."""
        score = 1.0
        if wiki_page.one_liner:
            score += 1.0
        if wiki_page.tags:
            score += 0.5
        if wiki_page.tech_principle:
            score += 0.8
        if wiki_page.product_impl:
            score += 0.8
        if wiki_page.user_feedback:
            score += 0.8
        if wiki_page.chat_notes:
            score += 0.6
        return round(min(score, 5.0), 2)

    def process_payload(
        self,
        payload: ChatToMemoryPayload,
        *,
        registry: ToolRegistry | None = None,
        write_notion: bool = False,
    ) -> MemoryProcessResult:
        """Merge, compile, quality-check, and optionally persist one payload."""
        merged = self.merge_payload(payload)
        page = self.compile_wiki_page(merged)
        score = self.quality_check(page)
        page.quality_score = score
        if score < 3.0:
            page.chat_notes = (page.chat_notes + "\n[regen-needed]")[:1800]

        notion_written = False
        queued = False
        if write_notion and registry is not None:
            notion_written, queued = self._persist_to_notion(page, registry)
        return MemoryProcessResult(
            wiki_page=page,
            quality_score=score,
            notion_written=notion_written,
            queued_for_retry=queued,
        )

    def _persist_to_notion(self, page: WikiPage, registry: ToolRegistry) -> tuple[bool, bool]:
        """Persist a wiki page to Notion or queue it for retry on failure."""
        if "upsert_notion_wiki" not in registry.names():
            self._enqueue(page)
            return False, True

        with self._file_lock():
            try:
                registry.execute(
                    "upsert_notion_wiki",
                    {"name": page.name, "one_liner": page.one_liner, "tags": page.tags},
                )
                return True, False
            except Exception:
                self._enqueue(page)
                return False, True

    def _enqueue(self, page: WikiPage) -> None:
        """Append a failed wiki write to the local retry queue."""
        queued: list[dict[str, Any]] = []
        if self.queue_path.exists():
            queued = json.loads(self.queue_path.read_text(encoding="utf-8"))
        queued.append(asdict(page))
        self.queue_path.write_text(json.dumps(queued, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize_layer(self, value: str) -> str | None:
        """Normalize legacy or localized source-layer values."""
        text = (value or "").strip()
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

    @contextmanager
    def _file_lock(self) -> Any:
        """Use a lock file for simple mutual exclusion."""
        for _ in range(40):
            try:
                self.lock_path.open("x", encoding="utf-8").close()
                break
            except FileExistsError:
                time.sleep(0.05)
        else:
            raise TimeoutError("memory lock acquisition timed out")
        try:
            yield
        finally:
            if self.lock_path.exists():
                self.lock_path.unlink()
