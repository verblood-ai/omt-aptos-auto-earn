"""Shared retry/backoff helper used by network-facing modules."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass
class RetryTelemetry:
    attempts: int = 0
    retries: int = 0
    total_delay_seconds: float = 0.0
    exhausted: bool = False
    last_error: str = ""


async def execute_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    attempts: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
    jitter_ratio: float,
    is_retryable: Callable[[BaseException], bool],
    sleep_func: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> tuple[bool, Any, Optional[BaseException], RetryTelemetry]:
    """
    Execute an async operation with exponential backoff + jitter.

    Returns:
        (ok, value, error, telemetry)
    """
    telemetry = RetryTelemetry()
    last_error: Optional[BaseException] = None
    safe_attempts = max(1, int(attempts))
    base = max(0.0, float(base_delay_seconds))
    max_delay = max(base, float(max_delay_seconds))
    jitter = max(0.0, min(1.0, float(jitter_ratio)))

    for attempt in range(1, safe_attempts + 1):
        telemetry.attempts = attempt
        try:
            value = await operation()
            return True, value, None, telemetry
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            telemetry.last_error = str(exc)
            if attempt >= safe_attempts or not is_retryable(exc):
                telemetry.exhausted = attempt >= safe_attempts
                return False, None, exc, telemetry

            telemetry.retries += 1
            delay = min(max_delay, base * (2 ** (attempt - 1)))
            if jitter > 0:
                jitter_part = delay * jitter * random.random()
                delay += jitter_part
            telemetry.total_delay_seconds += delay
            await sleep_func(delay)

    telemetry.exhausted = True
    if last_error is not None:
        telemetry.last_error = str(last_error)
    return False, None, last_error, telemetry
