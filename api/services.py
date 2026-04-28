"""Shared service container and helper methods for the FastAPI layer."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..agents import (
    ChatAgent,
    ExecutionLogAnalyzer,
    MemoryAgent,
    NoveltyScorerAgent,
    OrchestratorAgent,
    RecommenderAgent,
)
from ..data import get_db, init_db
from ..runtime.tool_registry import ToolRegistry
from ..runtime.llm_client import LLMClient
from ..skills import SkillManager, SkillStorage

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data"
MEMORY_ROOT = DATA_ROOT / "memory"
SKILLS_ROOT = DATA_ROOT / "skills"
PREFERENCES_PATH = DATA_ROOT / "preferences.json"

DEFAULT_PREFERENCES: dict[str, Any] = {
    "interests": ["AI agents", "developer tools", "LLM applications"],
    "preferred_platforms": ["product_hunt", "reddit", "arxiv"],
    "exploration_ratio": 0.3,
    "feed_size": 12,
    "exploration_queries": ["open source AI", "multimodal AI", "AI workflow automation"],
    "boosted_topics": [],
    "suppressed_topics": [],
}


@dataclass
class AppServices:
    """Runtime service container shared by API handlers."""

    registry: ToolRegistry
    db_path: str | None = None
    memory_dir: str | Path = MEMORY_ROOT
    skill_dir: str | Path = SKILLS_ROOT
    preferences_path: str | Path = PREFERENCES_PATH

    def __post_init__(self) -> None:
        """Initialize stateful collaborators and storage paths."""
        init_db(self.db_path)
        self.memory_dir = Path(self.memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.preferences_path = Path(self.preferences_path)
        self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
        self.saved_items_path = self.memory_dir / "saved_items.json"
        self.skill_manager = SkillManager(storage=SkillStorage(self.skill_dir))
        self.memory_agent = MemoryAgent(self.memory_dir)
        self.skill_manager.ensure_initial_crawler_skills(self.registry)
        self._feed_cache: dict[str, Any] | None = None
        self._llm_client: LLMClient | None = None

    def load_preferences(self) -> dict[str, Any]:
        """Load preferences from disk or return defaults."""
        if not self.preferences_path.exists():
            remote = self._load_preferences_from_notion()
            if remote is not None:
                merged = dict(DEFAULT_PREFERENCES)
                merged.update(remote)
                self.preferences_path.write_text(
                    json.dumps(merged, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return merged
            return dict(DEFAULT_PREFERENCES)
        loaded = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_PREFERENCES)
        merged.update(loaded)
        return merged

    def save_preferences(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge and persist a preference update."""
        current = self.load_preferences()
        current.update({key: value for key, value in patch.items() if value is not None})
        self.preferences_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._sync_preferences_to_notion(current)
        self._feed_cache = None
        return current

    def build_feed(self) -> dict[str, Any]:
        """Run the current feed pipeline and return feed plus diagnostics."""
        preferences = self.load_preferences()
        cache_preferences = dict(preferences)
        cache_preferences.pop("exploration_ratio", None)
        cache_key = json.dumps(cache_preferences, sort_keys=True, ensure_ascii=False)
        now = time.monotonic()
        if (
            self._feed_cache is not None
            and self._feed_cache["key"] == cache_key
            and self._feed_cache["expires_at"] > now
        ):
            return self._feed_cache["payload"]
        if not self.registry.names():
            raise HTTPException(status_code=503, detail="No crawler tools registered")

        try:
            plan = OrchestratorAgent(db_path=self.db_path).build_daily_plan(preferences)
            from ..agents import CrawlerAgent  # local import to avoid cyclic module init edges

            crawler = CrawlerAgent(
                registry=self.registry,
                skill_manager=self.skill_manager,
                cache_dir=self.memory_dir.parent / "crawler_cache",
            )
            crawl_result = crawler.crawl(plan.tasks)
            if not crawl_result.items:
                raise HTTPException(status_code=502, detail="Crawler returned no items")

            known_item_ids = self._known_item_ids()
            scored = NoveltyScorerAgent().score_batch(crawl_result.items, known_item_ids=known_item_ids)
            feed_result = RecommenderAgent(db_path=self.db_path).build_feed(scored, preferences=preferences)
            scored_by_id = {item.item_id: item for item in scored}
            self._localize_feed_items(feed_result.feed, scored_by_id=scored_by_id)
            payload = {
                "feed": feed_result.feed,
                "diagnostics": {
                    "tasks_executed": crawl_result.tasks_executed,
                    "total_items": crawl_result.report.total_items,
                    "cached_platforms": crawl_result.report.cached_platforms,
                    "per_platform_counts": crawl_result.report.per_platform_counts,
                    "used_stale_feed": False,
                },
                "filter_bubble_warning": feed_result.filter_bubble_warning,
            }
            self._feed_cache = {
                "key": cache_key,
                "expires_at": now + 180,
                "payload": payload,
            }
            return payload
        except Exception as exc:
            if self._feed_cache is not None and self._feed_cache.get("payload"):
                stale_payload = dict(self._feed_cache["payload"])
                diagnostics = dict(stale_payload.get("diagnostics", {}))
                diagnostics["used_stale_feed"] = True
                diagnostics["stale_reason"] = str(exc)
                stale_payload["diagnostics"] = diagnostics
                return stale_payload
            raise

    def record_action(
        self,
        *,
        item_id: str,
        action: str,
        item_title: str = "",
        one_liner: str = "",
        pool_type: str | None = None,
        novelty_label: str | None = None,
        source_type: str | None = None,
        chat_turns: int = 0,
    ) -> None:
        """Persist one user action row."""
        conn = get_db(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO user_actions (
                    item_id, item_title, action, pool_type, novelty_label, chat_turns
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (item_id, item_title, action, pool_type, novelty_label, chat_turns),
            )
            conn.commit()
        finally:
            conn.close()
        self._update_behavioral_preferences()
        if action == "save":
            self._save_item(
                item_id=item_id,
                item_title=item_title,
                one_liner=one_liner,
                pool_type=pool_type,
                source_type=source_type,
            )

    def answer_chat(
        self,
        *,
        query: str,
        product_id: str,
        product_name: str,
        max_per_tool: int = 2,
        persist_memory: bool = True,
        write_notion: bool = False,
    ) -> dict[str, Any]:
        """Run chat retrieval and optionally persist the result into memory."""
        if not self.registry.names():
            raise HTTPException(status_code=503, detail="No chat tools registered")

        result = ChatAgent(self.registry).answer_query(
            query,
            product_name=product_name,
            max_per_tool=max_per_tool,
        )
        payload = ChatAgent(self.registry).build_memory_payload(
            product_id=product_id,
            product_name=product_name,
            query=query,
            result=result,
        )

        memory_result = None
        if persist_memory:
            memory_result = self.memory_agent.process_payload(
                payload,
                registry=self.registry,
                write_notion=write_notion,
            )

        return {
            "result": result,
            "payload": payload,
            "memory_result": memory_result,
        }

    def dashboard_snapshot(self) -> dict[str, Any]:
        """Collect skill health, feed metrics, and execution summaries."""
        conn = get_db(self.db_path)
        try:
            feed_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS feed_items,
                    AVG(final_score) AS avg_final_score,
                    SUM(CASE WHEN pool_type='precision' THEN 1 ELSE 0 END) AS precision_items,
                    SUM(CASE WHEN pool_type='exploration' THEN 1 ELSE 0 END) AS exploration_items
                FROM feed_history
                """
            ).fetchone()
            action_row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN action='open' THEN 1 ELSE 0 END) AS opens,
                    SUM(CASE WHEN action LIKE 'skip%' THEN 1 ELSE 0 END) AS skips,
                    SUM(CASE WHEN action='save' THEN 1 ELSE 0 END) AS saves
                FROM user_actions
                """
            ).fetchone()
        finally:
            conn.close()

        analysis = ExecutionLogAnalyzer(db_path=self.db_path).analyze_recent_logs()
        skill_health = [
            {
                "skill_id": skill.skill_id,
                "skill_type": skill.skill_type,
                "success_rate": round(skill.success_rate, 3),
                "usage_count": skill.usage_count,
                "version": skill.version,
                "heal_required": skill.heal_required,
            }
            for skill in self.skill_manager.all_skills()
        ]
        return {
            "skill_health": skill_health,
            "feed_metrics": {
                "feed_items": int(feed_row["feed_items"] or 0),
                "avg_final_score": round(float(feed_row["avg_final_score"] or 0.0), 3),
                "precision_items": int(feed_row["precision_items"] or 0),
                "exploration_items": int(feed_row["exploration_items"] or 0),
                "opens": int(action_row["opens"] or 0),
                "skips": int(action_row["skips"] or 0),
                "saves": int(action_row["saves"] or 0),
            },
            "execution": asdict(analysis),
        }

    def search_wiki(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search the warmed local wiki cache by name, tag, or one-liner."""
        if not self.memory_agent.wiki_cache_path.exists():
            return []
        entries = json.loads(self.memory_agent.wiki_cache_path.read_text(encoding="utf-8"))
        needle = query.lower().strip()
        matches: list[dict[str, Any]] = []
        for entry in entries:
            haystack = " ".join(
                [
                    str(entry.get("name", "")),
                    str(entry.get("one_liner", "")),
                    " ".join(entry.get("tags", [])),
                ]
            ).lower()
            if needle and needle not in haystack:
                continue
            matches.append(
                {
                    "name": entry.get("name", ""),
                    "tags": entry.get("tags", []),
                    "one_liner": entry.get("one_liner", ""),
                    "weight": float(entry.get("weight", 1.0)),
                    "recall_count": int(entry.get("recall_count", 0)),
                }
            )
        matches.sort(key=lambda item: (item["weight"], item["recall_count"]), reverse=True)
        return matches[:limit]

    def _known_item_ids(self) -> set[str]:
        """Load item ids that appeared before today, not items generated in the current session."""
        conn = get_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT item_id FROM feed_history WHERE feed_date < ?",
                (date.today().isoformat(),),
            ).fetchall()
        finally:
            conn.close()
        return {row["item_id"] for row in rows}

    def _localize_feed_items(self, feed: Any, *, scored_by_id: dict[str, Any] | None = None) -> None:
        """Use one batched LLM call to rewrite feed cards into Chinese radar notes."""
        client = self._get_llm_client()
        if client is None:
            return

        items = [*feed.precision_pool, *feed.exploration_pool]
        if not items:
            return

        try:
            prompt_items = [
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "draft": item.one_liner,
                    "pool_type": item.pool_type,
                    "source_platform": getattr(scored_by_id.get(item.item_id), "source_platform", "") if scored_by_id else "",
                    "source_layer": getattr(scored_by_id.get(item.item_id), "source_layer", "") if scored_by_id else "",
                    "summary": getattr(scored_by_id.get(item.item_id), "summary", "") if scored_by_id else "",
                    "novelty_reason": getattr(scored_by_id.get(item.item_id), "novelty_reason", "") if scored_by_id else "",
                    "memory_brief": self._build_memory_brief(item.title),
                }
                for item in items
            ]
            response = client.call(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "请把下面这些 AI 雷达条目改写成中文情报卡片正文。\n"
                            "目标风格：让用户通过卡片迅速理解一个闭环。\n"
                            "这个闭环至少要覆盖：它是什么新热点、用了什么技术、和以前相比改进了什么、可能带来什么新方向、为什么和用户已有知识有关。\n\n"
                            "输出要求：\n"
                            "1. 只输出简体中文，保留必要的英文术语，如 model-native、sandbox、token、benchmark。\n"
                            "2. 每条写成 4-6 行的完整内容块，总长度 120-240 个中文字符。\n"
                            "3. 第一行必须以标题中的主体开头，比如“OpenAI Agents SDK 把...”“MCP 现在...”“CrewAI Flows 提出...”。\n"
                            "4. 如果适合，用短横线列 2-4 个关键点；如果不适合，就写成紧凑短段落。\n"
                            "5. 要写出技术判断、产品含义、为什么建议继续跟进，不要空话。\n"
                            "6. 不要输出标题、摘要、标签这种字段名，不要 markdown 代码块。\n"
                            "7. 不要只翻译标题；要明确写出“它提出了什么 / 改变了什么 / 对使用者意味着什么”。\n"
                            "8. 如果提供了历史知识摘要，要把“它和旧知识的关联”自然写进去，帮助用户理解为什么这条值得继续了解。\n"
                            "9. 历史知识只是辅助，不要瞎编没有提供过的旧结论。\n"
                            "10. 严格输出 JSON 数组，元素格式为 {\"item_id\":\"...\",\"one_liner\":\"...\"}。\n\n"
                            "建议结构可以接近这样：\n"
                            "第 1 行：XX 产品 / XX 技术这次提出了什么\n"
                            "第 2 行：它主要用了什么技术或方法\n"
                            "第 3 行：和以前相比具体改进在哪里\n"
                            "第 4 行：这可能把方向带到哪里，或为什么值得继续跟\n"
                            "第 5 行：如果有历史知识，补一句它和旧知识库的关联\n\n"
                            "参考风格示例：\n"
                            "[\n"
                            "  {\n"
                            "    \"item_id\": \"demo-1\",\n"
                            "    \"one_liner\": \"OpenAI Agents SDK 这次把 model-native harness 和 sandbox execution 往统一基建上收。\\n- 技术核心是把推理、orchestration、memory 和受控执行环境拆成更清楚的层\\n- 和以前零散拼工具相比，它更强调 agent runtime 的结构化边界\\n- 这会把后续竞争点从接了多少工具，推向 harness 怎么管理工具和上下文\\n- 如果你的旧知识库里一直在区分 runtime / harness，这条会直接补上那块认知闭环。\"\n"
                            "  },\n"
                            "  {\n"
                            "    \"item_id\": \"demo-2\",\n"
                            "    \"one_liner\": \"MCP 现在越来越像标准插件层，而不只是一个玩具协议。\\n- 它用的是统一的 tool/server 协议，把接入方式和生态边界一起标准化\\n- 和以前每家各写一套工具桥接相比，复用性和迁移性都更高\\n- 这会让 agent 产品的下一阶段重点转向工具治理，而不只是工具数量\\n- 如果你旧知识库里已经在关注插件层或 tool abstraction，这条值得连起来看。\"\n"
                            "  }\n"
                            "]\n\n"
                            "现在处理这批卡片：\n"
                            + json.dumps(prompt_items, ensure_ascii=False)
                        ),
                    }
                ],
                system=(
                    "你是 AI 产品雷达编辑。"
                    "你的任务不是翻译标题，而是把多来源线索重写成可快速扫描的中文情报卡片。"
                    "每条都要先点名主体，再解释提出了什么变化。"
                    "语气要克制、专业、有判断。"
                    "只输出合法 JSON，不要解释，不要 markdown。"
                ),
                max_tokens=2200,
            )
            localized = json.loads(response.text)
            by_id = {
                entry.get("item_id"): str(entry.get("one_liner", "")).strip()
                for entry in localized
                if entry.get("item_id")
            }
            for item in items:
                text = by_id.get(item.item_id)
                if text:
                    item.one_liner = self._normalize_radar_note(text, item.title)
        except Exception:
            return

    def _build_memory_brief(self, title: str) -> str:
        """Build a short memory brief from local wiki cache or Notion search."""
        matches = self._find_memory_matches(title, limit=3)
        if not matches:
            return ""

        lines: list[str] = []
        for match in matches:
            name = str(match.get("name", "")).strip()
            one_liner = str(match.get("one_liner", "")).strip()
            tags = [str(tag).strip() for tag in match.get("tags", []) if str(tag).strip()]
            weight = match.get("weight")
            recall_count = match.get("recall_count")

            parts = [part for part in [name, one_liner] if part]
            if tags:
                parts.append(f"标签={','.join(tags[:4])}")
            if weight is not None:
                parts.append(f"权重={weight}")
            if recall_count is not None:
                parts.append(f"召回={recall_count}")
            lines.append(" | ".join(parts[:4]))
        return "\n".join(lines[:3])

    def _find_memory_matches(self, title: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Find relevant wiki memory entries without flooding the prompt."""
        local_matches = self._search_local_wiki_cache(title, limit=limit)
        if local_matches:
            return local_matches
        return self._query_notion_memory(title, limit=limit)

    def _search_local_wiki_cache(self, title: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Search the warmed local wiki cache by normalized title overlap."""
        if not self.memory_agent.wiki_cache_path.exists():
            return []

        try:
            entries = json.loads(self.memory_agent.wiki_cache_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        query = self._normalize_memory_query(title)
        if not query:
            return []

        scored_entries: list[tuple[float, dict[str, Any]]] = []
        query_tokens = set(query.split())
        for entry in entries:
            name = str(entry.get("name", ""))
            one_liner = str(entry.get("one_liner", ""))
            haystack = self._normalize_memory_query(f"{name} {one_liner}")
            if not haystack:
                continue

            overlap = self._token_overlap_score(query_tokens, set(haystack.split()))
            if query in haystack:
                overlap += 1.0
            if overlap <= 0:
                continue

            weight = float(entry.get("weight", 1.0) or 1.0)
            recall = int(entry.get("recall_count", 0) or 0)
            score = overlap + min(weight, 3.0) * 0.15 + min(recall, 10) * 0.03
            scored_entries.append((score, entry))

        scored_entries.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in scored_entries[:limit]]

    def _query_notion_memory(self, title: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Fallback to live Notion search when no local cache match is available."""
        if "query_notion_wiki" not in self.registry.names():
            return []
        try:
            raw = self.registry.execute("query_notion_wiki", {"query": title, "max_results": limit})
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return []
        return [entry for entry in data[:limit] if isinstance(entry, dict)]

    @staticmethod
    def _normalize_memory_query(text: str) -> str:
        """Normalize product names/titles for fuzzy matching."""
        cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
        return " ".join(cleaned.split())

    @staticmethod
    def _token_overlap_score(left: set[str], right: set[str]) -> float:
        """Compute a simple overlap score for fuzzy local memory retrieval."""
        if not left or not right:
            return 0.0
        overlap = left & right
        if not overlap:
            return 0.0
        return len(overlap) / max(1, min(len(left), len(right)))

    def _normalize_radar_note(self, text: str, title: str) -> str:
        """Nudge model output toward a subject-first compact radar note."""
        cleaned = text.strip().replace("\r\n", "\n")

        normalized_title = title.rstrip(" :：-")
        if normalized_title and not cleaned.startswith(normalized_title):
            first_line, *rest = cleaned.split("\n")
            if first_line.startswith(("这次", "这条", "最值得", "重点是", "核心是")):
                cleaned = f"{normalized_title} {first_line}"
                if rest:
                    cleaned += "\n" + "\n".join(rest)
            else:
                cleaned = f"{normalized_title}：{cleaned}"

        if "\n" not in cleaned:
            parts = [part.strip() for part in cleaned.split("。") if part.strip()]
            if len(parts) >= 3:
                cleaned = f"{parts[0]}。\n- {parts[1]}\n- {parts[2]}"
                if len(parts) > 3:
                    cleaned += f"\n{parts[3]}。"
            elif len(parts) == 2:
                cleaned = f"{parts[0]}。\n- {parts[1]}"
        return cleaned.strip()

    def _get_llm_client(self) -> LLMClient | None:
        """Return a lazily constructed client when LLM credentials are available."""
        if self._llm_client is not None:
            return self._llm_client
        if not os.getenv("LLM_API_KEY"):
            return None
        try:
            self._llm_client = LLMClient(timeout=45.0, max_retries=2)
        except Exception:
            return None
        return self._llm_client

    def _save_item(
        self,
        *,
        item_id: str,
        item_title: str,
        one_liner: str,
        pool_type: str | None,
        source_type: str | None,
    ) -> None:
        """Persist a saved item locally and mirror it to Notion when configured."""
        saved_items: list[dict[str, Any]] = []
        if self.saved_items_path.exists():
            saved_items = json.loads(self.saved_items_path.read_text(encoding="utf-8"))
        existing = next((entry for entry in saved_items if entry.get("item_id") == item_id), None)

        if existing is None:
            existing = {
                "item_id": item_id,
                "title": item_title,
                "one_liner": one_liner,
                "pool_type": pool_type,
                "source_type": source_type,
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "notion_synced": False,
            }
            saved_items.append(existing)
        else:
            existing["title"] = item_title or existing.get("title", "")
            existing["one_liner"] = one_liner or existing.get("one_liner", "")
            existing["pool_type"] = pool_type or existing.get("pool_type")
            existing["source_type"] = source_type or existing.get("source_type")
            existing.setdefault("saved_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
            existing.setdefault("notion_synced", False)

        self.saved_items_path.write_text(json.dumps(saved_items, ensure_ascii=False, indent=2), encoding="utf-8")

        if "upsert_notion_wiki" not in self.registry.names():
            return
        if existing.get("notion_synced"):
            return
        try:
            tags = [tag for tag in [source_type, pool_type, "saved_feed_item"] if tag]
            self.registry.execute(
                "upsert_notion_wiki",
                {"name": item_title, "one_liner": one_liner or item_title, "tags": tags},
            )
            existing["notion_synced"] = True
            self.saved_items_path.write_text(
                json.dumps(saved_items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            return

    def _load_preferences_from_notion(self) -> dict[str, Any] | None:
        """Try to hydrate the local preferences file from the mirrored Notion page."""
        if "load_notion_preferences" not in self.registry.names():
            return None
        try:
            raw = self.registry.execute("load_notion_preferences", {"page_id": ""})
            payload = json.loads(raw) if isinstance(raw, str) else raw
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _sync_preferences_to_notion(self, profile: dict[str, Any]) -> None:
        """Mirror the latest preferences snapshot to the configured Notion page."""
        if "sync_notion_preferences" not in self.registry.names():
            return
        try:
            self.registry.execute("sync_notion_preferences", {"profile": profile, "page_id": ""})
        except Exception:
            return

    def _update_behavioral_preferences(self) -> None:
        """Derive a lightweight topic preference delta from recent user actions."""
        current = self.load_preferences()
        boosted_topics, suppressed_topics = self._derive_behavioral_topics()
        changed = (
            current.get("boosted_topics") != boosted_topics
            or current.get("suppressed_topics") != suppressed_topics
        )
        if not changed:
            return

        updated = dict(current)
        updated["boosted_topics"] = boosted_topics
        updated["suppressed_topics"] = suppressed_topics
        self.preferences_path.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._sync_preferences_to_notion(updated)
        self._feed_cache = None

    def _derive_behavioral_topics(self, *, days: int = 7, limit: int = 5) -> tuple[list[str], list[str]]:
        """Summarize recent behavior into positive and negative topic lists."""
        cutoff = time.time() - days * 24 * 60 * 60
        cutoff_text = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(cutoff))
        action_weights = {
            "save": 3,
            "open": 2,
            "skip": -2,
            "skip_future": -3,
        }
        token_scores: dict[str, int] = {}

        conn = get_db(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT item_title, action
                FROM user_actions
                WHERE created_at >= ?
                ORDER BY created_at DESC
                """,
                (cutoff_text,),
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            weight = action_weights.get(str(row["action"]), 0)
            if weight == 0:
                continue
            for token in self._extract_topic_tokens(str(row["item_title"] or "")):
                token_scores[token] = token_scores.get(token, 0) + weight

        positives = sorted(
            (token for token, score in token_scores.items() if score >= 3),
            key=lambda token: (-token_scores[token], token),
        )
        negatives = sorted(
            (token for token, score in token_scores.items() if score <= -3),
            key=lambda token: (token_scores[token], token),
        )

        boosted_topics = positives[:limit]
        suppressed_topics = [token for token in negatives if token not in boosted_topics][:limit]
        return boosted_topics, suppressed_topics

    @staticmethod
    def _extract_topic_tokens(text: str) -> list[str]:
        """Extract stable keyword-like tokens from a card title for lightweight preference learning."""
        stopwords = {
            "about",
            "agent",
            "agents",
            "and",
            "beta",
            "build",
            "for",
            "from",
            "have",
            "into",
            "looking",
            "more",
            "open",
            "source",
            "team",
            "that",
            "their",
            "this",
            "tool",
            "using",
            "with",
            "your",
        }
        tokens: list[str] = []
        for match in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()):
            token = match.strip("_-")
            if len(token) < 4 or token in stopwords:
                continue
            if token not in tokens:
                tokens.append(token)
        return tokens[:8]
