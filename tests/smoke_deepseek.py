"""Live smoke test: call DeepSeek through the runtime end-to-end.

Run manually:
    python -m ai_radar.tests.smoke_deepseek

Skipped under pytest by default (no `test_` prefix on functions that hit network).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from ai_radar.runtime.agent_loop import AgentConfig, run_agent
from ai_radar.runtime.llm_client import LLMClient
from ai_radar.runtime.observability import Observability
from ai_radar.runtime.permission_gate import AgentPolicy
from ai_radar.runtime.tool_registry import Tool, ToolRegistry


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    print(f"Model:    {os.getenv('LLM_MODEL')}")
    print(f"Base URL: {os.getenv('LLM_BASE_URL')}")

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="add",
            description="Add two integers and return the sum.",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
            handler=lambda a, b: str(a + b),
        )
    )

    client = LLMClient()
    obs = Observability()
    config = AgentConfig(
        name="smoke_agent",
        system_prompt="You are a calculator agent. Use the `add` tool to compute sums.",
        policy=AgentPolicy.of("smoke_agent", ["add"]),
        max_turns=4,
    )

    result = run_agent(
        config,
        initial_user_message="What is 17 + 25? Use the add tool, then tell me the result.",
        client=client,
        tools=registry,
        observability=obs,
    )

    print(f"\nturns:    {result.turns}")
    print(f"stopped:  {result.stopped_reason}")
    print(f"final:    {result.final_text}")
    obs.close()


if __name__ == "__main__":
    main()
