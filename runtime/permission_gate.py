"""Permission gate: per-Agent tool whitelist (PRD section 3.4 ②)."""
from __future__ import annotations

from dataclasses import dataclass


class PermissionDenied(Exception):
    pass


@dataclass(frozen=True)
class AgentPolicy:
    name: str
    allowed_tools: frozenset[str]

    @classmethod
    def of(cls, name: str, allowed: list[str]) -> "AgentPolicy":
        return cls(name=name, allowed_tools=frozenset(allowed))


class PermissionGate:
    """Validate tool calls against the agent's policy before execution."""

    def __init__(self, policy: AgentPolicy) -> None:
        self.policy = policy

    def check(self, tool_name: str) -> None:
        if tool_name not in self.policy.allowed_tools:
            raise PermissionDenied(
                f"Agent '{self.policy.name}' is not allowed to call tool '{tool_name}'. "
                f"Allowed: {sorted(self.policy.allowed_tools)}"
            )
