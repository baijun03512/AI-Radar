"""Self-healing: retry failed tool calls with exponential backoff."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class RetryOutcome:
    success: bool
    result: Any = None
    error: str = ""
    attempts: int = 0


def retry_tool_call(
    fn: Callable[[], Any],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> RetryOutcome:
    """Run `fn` up to max_attempts. Exponential backoff on raised exceptions."""
    last_err = ""
    for attempt in range(1, max_attempts + 1):
        try:
            result = fn()
            return RetryOutcome(success=True, result=result, attempts=attempt)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < max_attempts:
                sleep(base_delay * (2 ** (attempt - 1)))
    return RetryOutcome(success=False, error=last_err, attempts=max_attempts)
