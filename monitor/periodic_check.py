"""
Periodic background balance/health checker.

Runs probes on all managed providers at configurable intervals
and updates the balance cache.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Callable

import tenacity
from tenacity import (
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger("astrbot.api_mgr")

# Retry configuration for balance probes
RETRY_CONFIG = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)


class PeriodicBalanceChecker:
    """Runs periodic balance probes for all managed providers."""

    def __init__(
        self,
        interval_seconds: float = 3600.0,  # Default: check every hour
        on_result: Callable | None = None,  # Callback: async fn(provider_id, balance_info)
    ):
        self._interval = interval_seconds
        self._on_result = on_result
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_run: dict[str, float] = {}
        self._results: dict[str, dict] = {}

    async def start(self, probe_fn: Callable, providers: list[dict]) -> None:
        """Start the periodic checker.

        Args:
            probe_fn: Async callable (provider_id, api_key, base_url, model) → BalanceInfo.
            providers: List of provider dicts with id, type, api_key, base_url, model.
        """
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop(probe_fn, providers))
        logger.info(
            f"PeriodicBalanceChecker: Started (interval={self._interval}s, "
            f"providers={len(providers)})"
        )

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PeriodicBalanceChecker: Stopped")

    @tenacity.retry(**RETRY_CONFIG)
    async def _probe_with_retry(
        self,
        probe_fn: Callable,
        p_type: str,
        api_key: str,
        base_url: str,
        model_name: str,
    ) -> Any:
        """Probe a provider with automatic retry using tenacity."""
        return await probe_fn(p_type, api_key, base_url, model_name)

    async def run_once(self, probe_fn: Callable, providers: list[dict]) -> dict[str, dict]:
        """Run one round of probes and return results."""
        results = {}
        logger.info(f"PeriodicBalanceChecker: Running probes for {len(providers)} providers...")

        for p in providers:
            p_id = p["id"]
            p_type = p.get("type", "none")
            api_key = p.get("api_key", "")
            base_url = p.get("base_url", "")
            model_name = p.get("model", "")

            if p_type == "none" or not api_key:
                continue

            try:
                start = time.time()
                # Use tenacity-wrapped probe for automatic retry
                result = await self._probe_with_retry(
                    probe_fn, p_type, api_key, base_url, model_name
                )
                elapsed_ms = (time.time() - start) * 1000

                if result.error:
                    logger.warning(
                        f"PeriodicBalanceChecker: {p_id} probe FAILED ({elapsed_ms:.0f}ms): {result.error}"
                    )
                else:
                    logger.debug(
                        f"PeriodicBalanceChecker: {p_id} OK ({elapsed_ms:.0f}ms): "
                        f"remaining={result.remaining}"
                    )

                results[p_id] = result.to_dict()
                self._last_run[p_id] = time.time()
                self._results[p_id] = result.to_dict()

                if self._on_result:
                    try:
                        await self._on_result(p_id, result.to_dict())
                    except Exception as cb_err:
                        logger.error(f"PeriodicBalanceChecker: on_result callback failed: {cb_err}")

            except tenacity.RetryError as e:
                logger.error(f"PeriodicBalanceChecker: Probe '{p_id}' failed after retries: {e.last_attempt.exception()}")
                self._last_run[p_id] = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"PeriodicBalanceChecker: Probe '{p_id}' raised: {e}")

        logger.info(f"PeriodicBalanceChecker: Round complete ({len(results)} results)")
        return results

    def get_results(self) -> dict[str, dict]:
        return dict(self._results)

    def get_last_run(self, provider_id: str) -> float:
        return self._last_run.get(provider_id, 0.0)

    async def _run_loop(self, probe_fn: Callable, providers: list[dict]) -> None:
        while self._running:
            try:
                await self.run_once(probe_fn, providers)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"PeriodicBalanceChecker: Loop error: {e}", exc_info=True)

            await asyncio.sleep(self._interval)