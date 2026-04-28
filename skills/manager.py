"""Skill loading, matching, execution, and runtime learning."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..runtime.self_healing import retry_tool_call
from ..runtime.tool_registry import ToolRegistry
from .bootstrap import default_crawler_skills
from .models import Skill, SkillExecutionResult, SkillMatch
from .storage import SkillStorage


class SkillManager:
    """Coordinate skill storage, selection, execution, and health updates."""

    def __init__(
        self,
        *,
        storage: SkillStorage | None = None,
        heal_threshold: float = 0.8,
        min_usage_for_heal: int = 3,
    ) -> None:
        self.storage = storage or SkillStorage()
        self.heal_threshold = heal_threshold
        self.min_usage_for_heal = min_usage_for_heal
        self._skills: dict[str, Skill] = {}
        self.load_all()

    def load_all(self) -> list[Skill]:
        """Load all persisted skills into memory."""
        loaded = self.storage.load_all()
        self._skills = {skill.skill_id: skill for skill in loaded}
        return loaded

    def all_skills(self) -> list[Skill]:
        """Return all cached skills."""
        return list(self._skills.values())

    def get(self, skill_id: str) -> Skill:
        """Return one cached skill."""
        return self._skills[skill_id]

    def save(self, skill: Skill) -> Skill:
        """Persist and cache a skill."""
        self.storage.save(skill)
        self._skills[skill.skill_id] = skill
        return skill

    def ensure_initial_crawler_skills(self, registry: ToolRegistry) -> list[Skill]:
        """Create the three seed crawler skills when their tools are available."""
        created: list[Skill] = []
        available_tools = set(registry.names())
        existing_ids = set(self._skills)
        for skill in default_crawler_skills():
            if skill.skill_id in existing_ids:
                continue
            if skill.tool_name not in available_tools:
                continue
            self.save(skill)
            created.append(skill)
        return created

    def match_skill(
        self,
        *,
        skill_type: str,
        platform: str | None = None,
        source_layer: str | None = None,
        tool_name: str | None = None,
    ) -> Skill | None:
        """Match the best skill for a task."""
        matches: list[SkillMatch] = []
        for skill in self._skills.values():
            if skill.skill_type != skill_type:
                continue
            score = 0
            if platform and skill.platform == platform:
                score += 4
            elif platform:
                continue
            if source_layer and skill.source_layer == source_layer:
                score += 2
            if tool_name and skill.tool_name == tool_name:
                score += 3
            score += min(skill.version, 3)
            if skill.heal_required:
                score -= 2
            matches.append(SkillMatch(skill=skill, score=score))
        if not matches:
            return None
        matches.sort(
            key=lambda item: (
                item.score,
                item.skill.success_rate,
                item.skill.usage_count,
            ),
            reverse=True,
        )
        return matches[0].skill

    def execute_skill(
        self,
        skill_id: str,
        registry: ToolRegistry,
        *,
        skill_input: dict[str, Any] | None = None,
    ) -> SkillExecutionResult:
        """Execute a skill through the tool registry and update health stats."""
        skill = self.get(skill_id)
        tool_input = dict(skill.input_template)
        if skill_input:
            tool_input.update(skill_input)

        outcome = retry_tool_call(lambda: registry.execute(skill.tool_name, tool_input))
        skill.apply_execution_result(
            success=outcome.success,
            heal_threshold=self.heal_threshold,
            min_usage_for_heal=self.min_usage_for_heal,
        )
        self.save(skill)

        return SkillExecutionResult(
            skill_id=skill.skill_id,
            tool_name=skill.tool_name,
            success=outcome.success,
            output=outcome.result,
            error=outcome.error,
            reused=True,
            heal_triggered=skill.heal_required,
        )

    def execute_tool_with_runtime_learning(
        self,
        *,
        registry: ToolRegistry,
        platform: str,
        source_layer: str,
        tool_name: str,
        tool_input: dict[str, Any],
        description: str,
        logic: str,
        confidence: float = 0.9,
    ) -> SkillExecutionResult:
        """Run a tool directly and auto-create a crawler skill after success."""
        outcome = retry_tool_call(lambda: registry.execute(tool_name, tool_input))
        learned = None
        if outcome.success:
            learned = self.learn_crawler_skill(
                platform=platform,
                source_layer=source_layer,
                tool_name=tool_name,
                description=description,
                logic=logic,
                input_template=tool_input,
                confidence=confidence,
            )
        return SkillExecutionResult(
            skill_id=learned.skill_id if learned is not None else "",
            tool_name=tool_name,
            success=outcome.success,
            output=outcome.result,
            error=outcome.error,
            reused=False,
            heal_triggered=False,
        )

    def learn_crawler_skill(
        self,
        *,
        platform: str,
        source_layer: str,
        tool_name: str,
        description: str,
        logic: str,
        input_template: dict[str, Any] | None = None,
        confidence: float = 0.9,
    ) -> Skill | None:
        """Create a crawler skill from successful execution if confidence is high enough."""
        if confidence < 0.8:
            return None

        existing = self.match_skill(
            skill_type="crawler",
            platform=platform,
            source_layer=source_layer,
            tool_name=tool_name,
        )
        if existing is not None:
            return existing

        normalized_platform = platform.lower().replace(" ", "_")
        skill = Skill(
            skill_id=f"crawler_{normalized_platform}_v1",
            skill_type="crawler",
            platform=platform,
            source_layer=source_layer,
            tool_name=tool_name,
            description=description,
            logic=logic,
            input_template=input_template or {},
            created_by="runtime_learning",
            metadata={"confidence": confidence},
        )
        return self.save(skill)

    def skills_requiring_healing(self) -> list[Skill]:
        """Return skills flagged for regeneration."""
        return [skill for skill in self._skills.values() if skill.heal_required]

    def regenerate_skill(
        self,
        skill_id: str,
        *,
        logic: str | None = None,
        input_template: dict[str, Any] | None = None,
    ) -> Skill:
        """Bump a skill version and clear the heal flag after regeneration."""
        current = self.get(skill_id)
        updated = replace(
            current,
            version=current.version + 1,
            logic=logic or current.logic,
            input_template=input_template or current.input_template,
            heal_required=False,
            consecutive_failures=0,
        )
        return self.save(updated)

    def learn_response_template_skill(
        self,
        *,
        pattern_key: str,
        sample_query: str,
        template: str,
        confidence: float = 0.9,
    ) -> Skill | None:
        """Create a reusable response template skill for repeated chat patterns."""
        if confidence < 0.8:
            return None

        skill_id = f"response_template_{pattern_key}"
        existing = self._skills.get(skill_id)
        if existing is not None:
            return existing

        skill = Skill(
            skill_id=skill_id,
            skill_type="response_template",
            platform="chat",
            source_layer="cross_layer",
            tool_name="",
            description=f"Response template for repeated pattern: {sample_query[:80]}",
            logic=template,
            input_template={"sample_query": sample_query},
            created_by="runtime_learning",
            metadata={"confidence": confidence, "pattern_key": pattern_key},
        )
        return self.save(skill)
