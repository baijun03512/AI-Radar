"""Recommender agent for precision/exploration feed assembly."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..data import get_db, init_db
from ..schemas.contracts import Feed, FeedItem, ScoredItem

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
class FeedBuildResult:
    """Feed plus small diagnostics for the recommender."""

    feed: Feed
    filter_bubble_warning: bool


class RecommenderAgent:
    """Build the daily feed from scored items and user preferences."""

    DAILY_CANDIDATE_TOTAL = 12
    PRECISION_CANDIDATE_TOTAL = 7
    EXPLORATION_CANDIDATE_TOTAL = 5
    MAX_PER_PLATFORM = 3

    SOURCE_LAYER_ICONS = {
        "academic": "📚",
        "industry": "🏭",
        "community": "💬",
    }

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path
        init_db(db_path)

    def build_feed(
        self,
        scored_items: list[ScoredItem],
        *,
        preferences: dict[str, Any] | None = None,
    ) -> FeedBuildResult:
        """Build stable daily candidate pools, then persist feed_history."""
        pref = preferences or {}
        interests = [entry.lower() for entry in pref.get("interests", [])]

        precision_candidates = [item for item in scored_items if item.pool == "precision"]
        exploration_candidates = [item for item in scored_items if item.pool == "exploration"]
        if not exploration_candidates:
            exploration_candidates = sorted(scored_items, key=lambda item: item.novelty_score, reverse=True)
        if not precision_candidates:
            precision_candidates = sorted(scored_items, key=lambda item: item.novelty_score, reverse=True)

        precision_ranked = sorted(
            precision_candidates,
            key=lambda item: self._precision_score(item, interests),
            reverse=True,
        )
        exploration_ranked = sorted(
            exploration_candidates,
            key=lambda item: item.novelty_score,
            reverse=True,
        )

        precision_selected = self._select_diverse(
            precision_ranked,
            limit=min(self.PRECISION_CANDIDATE_TOTAL, self.DAILY_CANDIDATE_TOTAL),
        )
        exploration_selected = self._select_diverse(
            exploration_ranked,
            limit=min(self.EXPLORATION_CANDIDATE_TOTAL, self.DAILY_CANDIDATE_TOTAL),
        )
        precision_pool = [
            self._to_feed_item(item, self._precision_score(item, interests), "precision")
            for item in precision_selected
        ]
        exploration_pool = [
            self._to_feed_item(item, item.novelty_score, "exploration")
            for item in exploration_selected
        ]

        feed = Feed(
            feed_date=date.today().isoformat(),
            precision_pool=precision_pool,
            exploration_pool=exploration_pool,
        )
        self._persist_feed(feed, precision_selected, exploration_selected, interests)
        return FeedBuildResult(feed=feed, filter_bubble_warning=self._filter_bubble_warning())

    def _precision_score(self, item: ScoredItem, interests: list[str]) -> float:
        """Blend novelty and preference matching for the precision pool."""
        preference_score = self._preference_match(item, interests)
        return round(item.novelty_score * 0.4 + preference_score * 0.6, 3)

    def _preference_match(self, item: ScoredItem, interests: list[str]) -> float:
        """Simple keyword overlap against interest phrases."""
        if not interests:
            return 0.5
        text = f"{item.title} {item.summary}".lower()
        hits = sum(1 for interest in interests if interest in text)
        if hits:
            return min(1.0, 0.55 + 0.2 * hits)
        return 0.35 if self._normalize_layer(item.source_layer) == "industry" else 0.45

    def _to_feed_item(self, item: ScoredItem, final_score: float, pool_type: str) -> FeedItem:
        """Convert a scored item to a frontend feed contract."""
        normalized_layer = self._normalize_layer(item.source_layer)
        return FeedItem(
            item_id=item.item_id,
            title=item.title,
            one_liner=self._build_card_copy(item, normalized_layer),
            novelty_label=item.novelty_label,
            source_layer_icon=self.SOURCE_LAYER_ICONS.get(normalized_layer, "💬"),
            final_score=round(final_score, 3),
            pool_type=pool_type,
        )

    def _build_card_copy(self, item: ScoredItem, layer: str) -> str:
        """Create a Chinese radar-note fallback when LLM rewriting is unavailable."""
        focus = self._focus_sentence(item.title, item.summary)
        if layer == "academic":
            return (
                f"{item.title} 提出的重点是 {focus}。\n"
                f"- 先看它是不是在重写问题定义或评测方式\n"
                f"- 再看结论能不能迁移到真实产品决策\n"
                f"如果你最近在判断技术方向，这条适合放进待深读列表。"
            )
        if layer == "industry":
            return (
                f"{item.title} 这次更值得盯的是 {focus}。\n"
                f"- 先看它是不是已经进入真实工作流\n"
                f"- 再看它服务的是个人提效，还是团队级协作\n"
                f"如果这类能力继续收敛，后面很可能会变成产品标配。"
            )
        return (
            f"{item.title} 这波社区讨论主要集中在 {focus}。\n"
            f"- 适合拿来判断真实用户最在意的价值点\n"
            f"- 也能顺手看见摩擦点、门槛和落地阻力\n"
            f"如果社区讨论持续升温，往往意味着产品心智开始成形。"
        )

    def _focus_sentence(self, title: str, summary: str) -> str:
        """Infer one concise Chinese focus sentence from the raw title/summary."""
        text = f"{title} {summary}".lower()
        phrases: list[str] = []

        keyword_map = [
            (("token", "cost", "budget"), "智能体在真实任务里的 Token 成本与预算控制"),
            (("benchmark", "evaluation"), "新的基准评测方式和效果衡量标准"),
            (("workflow", "automation", "orchestration"), "多智能体编排与工作流自动化的落地方式"),
            (("local", "local-first", "edge"), "本地优先部署和端侧运行能力"),
            (("open source", "oss"), "开源能力是否已经具备复用价值"),
            (("production", "teams"), "团队在生产环境中的实际接入方式"),
            (("feedback", "user"), "真实用户对产品价值和摩擦点的反馈"),
            (("safety", "harm", "harms", "risk"), "模型风险、偏差与安全边界"),
            (("manufacturing", "operations"), "AI 在制造与运营流程中的切入点"),
            (("coding", "developer"), "AI 对编码与开发工作流的具体影响"),
            (("reasoning",), "模型推理能力在复杂任务中的表现"),
            (("agent",), "AI 智能体在复杂工作流里的执行方式"),
        ]
        for keywords, phrase in keyword_map:
            if any(keyword in text for keyword in keywords):
                phrases.append(phrase)

        if not phrases:
            cleaned = re.sub(r"\s+", " ", title.strip())
            if cleaned:
                return f"“{cleaned[:48]}”背后的核心问题"
            return "这个方向正在解决的核心问题"

        unique_phrases: list[str] = []
        for phrase in phrases:
            if phrase not in unique_phrases:
                unique_phrases.append(phrase)
        if len(unique_phrases) == 1:
            return unique_phrases[0]
        return f"{unique_phrases[0]}，以及{unique_phrases[1]}"

    def _normalize_layer(self, value: str) -> str:
        text = (value or "").strip()
        return LAYER_ALIASES.get(text, "community")

    def _select_diverse(self, ranked_items: list[ScoredItem], *, limit: int) -> list[ScoredItem]:
        """Select top items while capping same-platform saturation."""
        if limit <= 0:
            return []

        selected: list[ScoredItem] = []
        platform_counts: dict[str, int] = {}

        for item in ranked_items:
            platform = item.source_platform or "unknown"
            if platform_counts.get(platform, 0) >= self.MAX_PER_PLATFORM:
                continue
            selected.append(item)
            platform_counts[platform] = platform_counts.get(platform, 0) + 1
            if len(selected) >= limit:
                break

        if len(selected) >= limit:
            return selected

        selected_ids = {item.item_id for item in selected}
        for item in ranked_items:
            if item.item_id in selected_ids:
                continue
            selected.append(item)
            if len(selected) >= limit:
                break
        return selected

    def _persist_feed(
        self,
        feed: Feed,
        precision_items: list[ScoredItem],
        exploration_items: list[ScoredItem],
        interests: list[str],
    ) -> None:
        """Write feed selections into SQLite feed_history."""
        conn = get_db(self.db_path)
        try:
            for item in precision_items:
                conn.execute(
                    """
                    INSERT INTO feed_history (
                        feed_date, item_id, pool_type, final_score, novelty_score,
                        preference_score, novelty_label, source_platform, source_layer
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feed.feed_date,
                        item.item_id,
                        "precision",
                        self._precision_score(item, interests),
                        item.novelty_score,
                        self._preference_match(item, interests),
                        item.novelty_label,
                        item.source_platform,
                        self._normalize_layer(item.source_layer),
                    ),
                )
            for item in exploration_items:
                conn.execute(
                    """
                    INSERT INTO feed_history (
                        feed_date, item_id, pool_type, final_score, novelty_score,
                        preference_score, novelty_label, source_platform, source_layer
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feed.feed_date,
                        item.item_id,
                        "exploration",
                        item.novelty_score,
                        item.novelty_score,
                        0.0,
                        item.novelty_label,
                        item.source_platform,
                        self._normalize_layer(item.source_layer),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _filter_bubble_warning(self) -> bool:
        """Detect whether exploration items have been skipped for 5 straight days."""
        conn = get_db(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT DATE(created_at) AS action_date,
                       SUM(CASE WHEN pool_type='exploration' AND action='open' THEN 1 ELSE 0 END) AS opens,
                       SUM(CASE WHEN pool_type='exploration' AND action LIKE 'skip%' THEN 1 ELSE 0 END) AS skips
                FROM user_actions
                GROUP BY DATE(created_at)
                ORDER BY action_date DESC
                LIMIT 5
                """
            ).fetchall()
            if len(rows) < 5:
                return False
            return all(row["opens"] == 0 and row["skips"] > 0 for row in rows)
        finally:
            conn.close()

