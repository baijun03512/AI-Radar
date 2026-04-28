"""Mini Runtime core while-loop. Same shape for every Agent (PRD section 3.3).

Provider-neutral on top of OpenAI-compatible chat protocol:
  build context -> llm.call -> if tool_calls: gate.check + execute (with retry)
  -> log -> append tool result -> compress if needed -> repeat -> stop on end_turn.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional

from .context_manager import ContextManager
from .llm_client import LLMClient, LLMResponse, ToolCall
from .observability import LogEntry, Observability
from .permission_gate import AgentPolicy, PermissionDenied, PermissionGate
from .self_healing import retry_tool_call
from .tool_registry import ToolRegistry


@dataclass
class AgentConfig:
    name: str
    system_prompt: str
    policy: AgentPolicy
    token_budget: int = 8000
    max_turns: int = 10
    max_tokens_per_call: int = 2048


@dataclass
class AgentResult:
    final_text: str
    turns: int
    stopped_reason: str
    messages: list[dict] = field(default_factory=list)


def run_agent(
    config: AgentConfig,
    initial_user_message: str,
    *,
    client: LLMClient,
    tools: ToolRegistry,
    observability: Optional[Observability] = None,
) -> AgentResult:
    """Execute one agent run end-to-end. Returns the final assistant text."""
    obs = observability or Observability()
    gate = PermissionGate(config.policy)
    ctx = ContextManager(token_budget=config.token_budget)
    ctx.add_user(initial_user_message)

    tool_schemas = tools.schemas(config.policy.allowed_tools)

    turn = 0
    while turn < config.max_turns:
        turn += 1
        t0 = time.time()
        resp: LLMResponse = client.call(
            messages=ctx.messages,
            tools=tool_schemas or None,
            system=config.system_prompt,
            max_tokens=config.max_tokens_per_call,
        )
        call_ms = int((time.time() - t0) * 1000)

        # Stop condition: model returned plain text with no tool calls.
        if resp.stop_reason != "tool_use" or not resp.tool_calls:
            obs.log(
                LogEntry(
                    agent=config.name,
                    turn=turn,
                    reasoning=resp.text,
                    tool_called=None,
                    tool_input=None,
                    tool_result_summary="<end_turn>",
                    tool_success=True,
                    context_tokens=ctx.total_tokens(),
                    duration_ms=call_ms,
                )
            )
            return AgentResult(
                final_text=resp.text,
                turns=turn,
                stopped_reason=resp.stop_reason or "end_turn",
                messages=ctx.messages,
            )

        # Record assistant turn (text + tool_calls in OpenAI format).
        oa_tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.input, ensure_ascii=False),
                },
            }
            for tc in resp.tool_calls
        ]
        ctx.add_assistant(resp.text, oa_tool_calls, resp.reasoning_content)

        for tc in resp.tool_calls:
            payload, success, summary = _execute_one_tool(tc=tc, gate=gate, tools=tools)
            obs.log(
                LogEntry(
                    agent=config.name,
                    turn=turn,
                    reasoning=resp.text,
                    tool_called=tc.name,
                    tool_input=tc.input,
                    tool_result_summary=summary,
                    tool_success=success,
                    context_tokens=ctx.total_tokens(),
                    duration_ms=call_ms,
                )
            )
            ctx.add_tool_result(tc.id, payload)

        ctx.compress_if_needed()

    return AgentResult(
        final_text="<max_turns reached without end_turn>",
        turns=turn,
        stopped_reason="max_turns",
        messages=ctx.messages,
    )


def _execute_one_tool(
    *, tc: ToolCall, gate: PermissionGate, tools: ToolRegistry
) -> tuple[str, bool, str]:
    """Returns (payload_for_model, success, summary_for_log)."""
    try:
        gate.check(tc.name)
    except PermissionDenied as e:
        return f"Permission denied: {e}", False, "permission_denied"

    outcome = retry_tool_call(lambda: tools.execute(tc.name, tc.input))
    if outcome.success:
        payload = outcome.result if isinstance(outcome.result, str) else str(outcome.result)
        summary = payload[:200]
        return payload, True, summary
    return (
        f"Tool '{tc.name}' failed after {outcome.attempts} attempts: {outcome.error}",
        False,
        f"failed: {outcome.error[:150]}",
    )
