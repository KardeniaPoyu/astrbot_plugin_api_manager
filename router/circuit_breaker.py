"""
Async circuit breaker wrapping pybreaker (open source, battle-tested).

Uses pybreaker (https://github.com/danielfm/pybreaker) as the underlying
state machine, with an async-safe wrapper for use with aiohttp-based code.

Based on the Circuit Breaker pattern described in Michael T. Nygard's
"Release It!" and implemented by pybreaker.

Usage::

    registry = CircuitBreakerRegistry()
    breaker = registry.get("openai/gpt-4o")

    if breaker.is_open:
        # Skip this provider
        return

    try:
        result = await call_provider()
        breaker.record_success()
    except Exception as e:
        breaker.record_failure(e)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import pybreaker

logger = logging.getLogger("astrbot.api_mgr")

# State constants exported for convenience
STATE_CLOSED = pybreaker.STATE_CLOSED
STATE_OPEN = pybreaker.STATE_OPEN
STATE_HALF_OPEN = pybreaker.STATE_HALF_OPEN


_state_names = {
    STATE_CLOSED: "CLOSED",
    STATE_OPEN: "OPEN",
    STATE_HALF_OPEN: "HALF_OPEN",
}


@dataclass
class CircuitBreakerStats:
    """Runtime statistics for a circuit breaker."""
    provider_id: str = ""
    state: str = "CLOSED"
    failure_count: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_failure_time: float = 0.0
    opened_at: float = 0.0


class CircuitBreaker:
    """Async-safe wrapper around pybreaker.CircuitBreaker.

    pybreaker is synchronous by design. This wrapper keeps pybreaker's
    well-tested state machine while providing async-friendly record calls.
    """

    def __init__(
        self,
        provider_id: str,
        fail_max: int = 5,
        reset_timeout: float = 60.0,
    ):
        self._provider_id = provider_id
        self._breaker = pybreaker.CircuitBreaker(
            fail_max=fail_max,
            reset_timeout=reset_timeout,
        )
        self._total_failures = 0
        self._total_successes = 0
        self._last_failure_time = 0.0
        self._opened_at = 0.0
        self._prev_state = STATE_CLOSED

    # ── Properties ──────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self._breaker.current_state == STATE_OPEN

    @property
    def is_closed(self) -> bool:
        return self._breaker.current_state == STATE_CLOSED

    @property
    def is_half_open(self) -> bool:
        return self._breaker.current_state == STATE_HALF_OPEN

    @property
    def current_state(self) -> str:
        return self._breaker.current_state

    @property
    def failure_count(self) -> int:
        return self._breaker.fail_counter

    @property
    def stats(self) -> CircuitBreakerStats:
        return CircuitBreakerStats(
            provider_id=self._provider_id,
            state=_state_names.get(self._breaker.current_state, "UNKNOWN"),
            failure_count=self._breaker.fail_counter,
            total_failures=self._total_failures,
            total_successes=self._total_successes,
            last_failure_time=self._last_failure_time,
            opened_at=self._opened_at,
        )

    # ── Core API ────────────────────────────────────────────────────

    def _check_state_change(self) -> None:
        """Detect and log state transitions."""
        cur = self._breaker.current_state
        if cur != self._prev_state:
            logger.info(
                f"CB '{self._provider_id}': "
                f"{_state_names.get(self._prev_state, '?')} → "
                f"{_state_names.get(cur, '?')}"
            )
            if cur == STATE_OPEN:
                self._opened_at = time.time()
            self._prev_state = cur

    def record_success(self) -> None:
        """Record a successful call. Resets failure counter."""
        self._total_successes += 1
        # pybreaker: call with a no-op function to reset failure count
        try:
            self._breaker.call(lambda: None)
        except pybreaker.CircuitBreakerError:
            pass  # Breaker was OPEN — should not happen on success
        self._check_state_change()

    def record_failure(self, exc: Optional[Exception] = None) -> None:
        """Record a failed call. May trip the breaker to OPEN."""
        self._total_failures += 1
        self._last_failure_time = time.time()
        # pybreaker: call with a function that always raises
        try:
            self._breaker.call(_raise_error)
        except pybreaker.CircuitBreakerError:
            pass  # Breaker tripped → OPEN
        except ZeroDivisionError:
            pass  # Counted as failure, breaker still CLOSED
        self._check_state_change()

    def reset(self) -> None:
        """Force-reset the circuit breaker to CLOSED state."""
        self._breaker.close()
        self._total_failures = 0
        self._prev_state = STATE_CLOSED
        logger.info(f"CB '{self._provider_id}': Force reset → CLOSED")

    def half_open(self) -> None:
        """Force the circuit to HALF_OPEN state."""
        self._breaker.half_open()
        self._prev_state = STATE_HALF_OPEN
        logger.info(f"CB '{self._provider_id}': Force → HALF_OPEN")


def _raise_error() -> None:
    """Helper: always raises — used to simulate failure in pybreaker."""
    raise ZeroDivisionError


class CircuitBreakerRegistry:
    """Manages circuit breakers for multiple providers using pybreaker."""

    def __init__(
        self,
        fail_max: int = 5,
        reset_timeout: float = 60.0,
    ):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._fail_max = fail_max
        self._reset_timeout = reset_timeout

    def get(self, provider_id: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a provider."""
        if provider_id not in self._breakers:
            self._breakers[provider_id] = CircuitBreaker(
                provider_id=provider_id,
                fail_max=self._fail_max,
                reset_timeout=self._reset_timeout,
            )
        return self._breakers[provider_id]

    def get_all(self) -> dict[str, CircuitBreakerStats]:
        """Get stats for all registered breakers."""
        return {k: v.stats for k, v in self._breakers.items()}

    def remove(self, provider_id: str) -> None:
        self._breakers.pop(provider_id, None)

    def reset_all(self) -> None:
        for breaker in self._breakers.values():
            breaker.reset()