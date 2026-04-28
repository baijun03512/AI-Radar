"""Tool registry: register Python callables, expose OpenAI-format schemas."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Any]


class ToolRegistry:
    """In-memory registry for callable tools exposed to agents."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not registered")
        return self._tools[name]

    def names(self) -> list[str]:
        """Return registered tool names in registration order."""
        return list(self._tools)

    def schemas(self, allowed: frozenset[str] | set[str] | list[str] | None = None) -> list[dict]:
        """Return OpenAI-format function-calling schemas, filtered by `allowed`."""
        names = self._tools.keys() if allowed is None else [n for n in self._tools if n in allowed]
        return [
            {
                "type": "function",
                "function": {
                    "name": (t := self._tools[n]).name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for n in names
        ]

    def execute(self, name: str, tool_input: dict) -> Any:
        tool = self.get(name)
        return tool.handler(**tool_input)
