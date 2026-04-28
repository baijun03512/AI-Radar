"""Skill data structures for crawler, response, and memory behaviors."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

SkillType = Literal["crawler", "response_template", "memory_weight"]
SkillCreator = Literal["runtime_learning", "manual"]


def utc_now() -> str:
    """Return the current UTC timestamp as ISO8601."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Skill:
    """Serializable skill metadata and health state."""

    skill_id: str
    skill_type: SkillType
    platform: str
    source_layer: str
    tool_name: str
    description: str
    logic: str
    input_template: dict[str, Any] = field(default_factory=dict)
    success_rate: float = 1.0
    created_by: SkillCreator = "manual"
    created_at: str = field(default_factory=utc_now)
    last_used: str = ""
    version: int = 1
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    heal_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the skill to a JSON-serializable mapping."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Skill":
        """Build a skill from a deserialized JSON mapping."""
        return cls(**payload)

    def apply_execution_result(
        self,
        *,
        success: bool,
        heal_threshold: float,
        min_usage_for_heal: int,
    ) -> None:
        """Update skill health after one execution result."""
        self.usage_count += 1
        self.last_used = utc_now()
        if success:
            self.success_count += 1
            self.consecutive_failures = 0
        else:
            self.failure_count += 1
            self.consecutive_failures += 1

        total = self.success_count + self.failure_count
        self.success_rate = self.success_count / total if total else 1.0
        self.heal_required = (
            self.usage_count >= min_usage_for_heal and self.success_rate < heal_threshold
        )


@dataclass
class SkillMatch:
    """A matched skill plus its ranking score."""

    skill: Skill
    score: int


@dataclass
class SkillExecutionResult:
    """Outcome of running one skill through a tool registry."""

    skill_id: str
    tool_name: str
    success: bool
    output: Any = None
    error: str = ""
    reused: bool = True
    heal_triggered: bool = False
