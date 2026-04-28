"""Crawler agent that reuses skills, executes tools, and emits structured items."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ..runtime.observability import LogEntry, Observability
from ..runtime.tool_registry import ToolRegistry
from ..schemas.contracts import CrawledItem
from ..skills import SkillManager
from .orchestrator import CrawlTask


@dataclass
class CrawlReport:
    """Summary of one crawler run."""

    total_items: int = 0
    duplicate_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    cached_platforms: list[str] = field(default_factory=list)
    per_platform_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class CrawlBatchResult:
    """Structured crawler output for downstream agents."""

    items: list[CrawledItem]
    report: CrawlReport
    tasks_executed: int


class CrawlerAgent:
    """Execute a batch of crawl tasks using persisted skills."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        skill_manager: SkillManager,
        observability: Observability | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.registry = registry
        self.skill_manager = skill_manager
        self.observability = observability
        self.cache_dir = Path(cache_dir) if cache_dir is not None else Path("data/crawler_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.skill_manager.ensure_initial_crawler_skills(registry)

    def crawl(self, tasks: list[CrawlTask]) -> CrawlBatchResult:
        """Execute all crawl tasks and return structured items plus a quality report."""
        report = CrawlReport()
        items: list[CrawledItem] = []
        seen: set[tuple[str, str]] = set()

        for turn, task in enumerate(tasks, start=1):
            task_items, used_cache, success, message = self._run_task(task)
            if success:
                report.success_count += 1
            else:
                report.failure_count += 1
            if used_cache:
                report.cached_platforms.append(task.platform)

            self._log_task(turn, task, success, message, len(task_items))

            for item in task_items:
                key = (item.item_id, item.source_url)
                if key in seen:
                    report.duplicate_count += 1
                    continue
                seen.add(key)
                items.append(item)
                report.per_platform_counts[item.source_platform] = (
                    report.per_platform_counts.get(item.source_platform, 0) + 1
                )

        report.total_items = len(items)
        return CrawlBatchResult(items=items, report=report, tasks_executed=len(tasks))

    def _run_task(self, task: CrawlTask) -> tuple[list[CrawledItem], bool, bool, str]:
        """Execute one task via a matched skill or tool-level runtime learning."""
        skill = self.skill_manager.match_skill(
            skill_type="crawler",
            platform=task.platform,
            source_layer=task.source_layer,
            tool_name=task.tool_name,
        )

        if skill is not None:
            result = self.skill_manager.execute_skill(
                skill.skill_id,
                self.registry,
                skill_input={"query": task.query, "max_results": task.max_results},
            )
        else:
            tool_name = task.tool_name or self._default_tool_name(task.platform)
            result = self.skill_manager.execute_tool_with_runtime_learning(
                registry=self.registry,
                platform=task.platform,
                source_layer=task.source_layer,
                tool_name=tool_name,
                tool_input={"query": task.query, "max_results": task.max_results},
                description=f"Runtime learned crawler for {task.platform}",
                logic=f"Execute {tool_name} for {task.platform} with query '{task.query}'.",
            )

        if result.success:
            parsed = self._parse_items(result.output, task)
            self._write_cache(task, parsed)
            return parsed, False, True, f"tool={result.tool_name}; items={len(parsed)}"

        cached = self._read_cache(task)
        if cached:
            return cached, True, False, f"fallback_cache={task.platform}; error={result.error}"
        return [], False, False, f"error={result.error}"

    def _default_tool_name(self, platform: str) -> str:
        """Map a platform to its default crawler tool name."""
        mapping = {
            "arxiv": "search_arxiv",
            "product_hunt": "search_product_hunt",
            "reddit": "search_reddit",
        }
        return mapping[platform]

    def _parse_items(self, output: Any, task: CrawlTask) -> list[CrawledItem]:
        """Parse a tool's JSON payload into CrawledItem records."""
        if isinstance(output, str):
            data = json.loads(output)
        else:
            data = output
        items: list[CrawledItem] = []
        for row in data:
            items.append(
                CrawledItem(
                    item_id=str(row.get("item_id", row.get("title", ""))),
                    title=row.get("title", ""),
                    summary=row.get("summary", ""),
                    source_platform=row.get("source_platform", task.platform),
                    source_layer=row.get("source_layer", task.source_layer),
                    source_url=row.get("source_url", ""),
                    published_at=row.get("published_at", ""),
                    fetched_at=row.get("fetched_at", ""),
                    raw_content=row.get("raw_content"),
                    pool=task.pool,  # propagate task pool designation
                )
            )
        return items

    def _cache_path(self, task: CrawlTask) -> Path:
        """Return the cache file path for a task."""
        filename = f"{task.platform}_{task.pool}_{date.today().isoformat()}.json"
        return self.cache_dir / filename

    def _latest_cache_path(self, task: CrawlTask) -> Path | None:
        """Return the newest cache file for a platform/pool pair."""
        pattern = f"{task.platform}_{task.pool}_*.json"
        matches = sorted(self.cache_dir.glob(pattern))
        return matches[-1] if matches else None

    def _write_cache(self, task: CrawlTask, items: list[CrawledItem]) -> None:
        """Persist successful crawl output for fallback reuse."""
        payload = [asdict(item) for item in items]
        self._cache_path(task).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_cache(self, task: CrawlTask) -> list[CrawledItem]:
        """Load the latest cached output for the same platform/pool pair."""
        path = self._latest_cache_path(task)
        if path is None:
            return []
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [CrawledItem(**row) for row in rows]

    def _log_task(
        self,
        turn: int,
        task: CrawlTask,
        success: bool,
        message: str,
        item_count: int,
    ) -> None:
        """Write one crawler task execution log entry when observability is enabled."""
        if self.observability is None:
            return
        self.observability.log(
            LogEntry(
                agent="crawler_agent",
                turn=turn,
                reasoning=f"pool={task.pool}; query={task.query}",
                tool_called=self._default_tool_name(task.platform),
                tool_input={"query": task.query, "max_results": task.max_results},
                tool_result_summary=f"{message}; item_count={item_count}",
                tool_success=success,
            )
        )
