"""
Routing balancer: selects the best provider from a group.

Supports strategies:
- priority: Try providers in order, skip exhausted ones.
- weighted: Weight-based probabilistic selection.
- round_robin: Rotate through providers evenly.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from .circuit_breaker import CircuitBreakerRegistry, STATE_OPEN

logger = logging.getLogger("astrbot.api_mgr")


class RoutingStrategy(Enum):
    PRIORITY = auto()  # First available wins (ordered list)
    WEIGHTED = auto()  # Probability-based selection
    ROUND_ROBIN = auto()  # Rotate through providers


@dataclass
class ProviderRoute:
    """A provider entry in a routing group."""
    provider_id: str
    weight: float = 1.0
    enabled: bool = True

    def __hash__(self):
        return hash(self.provider_id)


@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    selected_provider_id: str
    strategy: RoutingStrategy = RoutingStrategy.PRIORITY
    reason: str = ""
    fallback_chain: list[str] = field(default_factory=list)


class RoutingBalancer:
    """Selects the best provider from a routing group."""

    def __init__(
        self,
        circuit_breaker_registry: CircuitBreakerRegistry | None = None,
        balance_checker: Optional[Callable[[str], bool]] = None,
    ):
        self._cb_registry = circuit_breaker_registry or CircuitBreakerRegistry()
        self._balance_checker = balance_checker or (lambda _: True)
        self._route_counts: dict[str, int] = {}
        self._round_robin_index: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def _is_provider_available(self, route: ProviderRoute) -> bool:
        """Check if a provider route is available."""
        if not route.enabled:
            return False

        # Check circuit breaker
        breaker = self._cb_registry.get(route.provider_id)
        if breaker.is_open:
            logger.debug(f"Balancer: '{route.provider_id}' circuit is OPEN, skipping")
            return False

        # Check balance
        if not self._balance_checker(route.provider_id):
            return False

        return True

    async def route(
        self,
        group_name: str,
        routes: list[ProviderRoute],
        strategy: RoutingStrategy = RoutingStrategy.PRIORITY,
    ) -> RoutingDecision:
        """Select a provider from the given route list.

        Args:
            group_name: Name of the routing group (for stats).
            routes: Ordered list of provider routes.
            strategy: The routing strategy to use.

        Returns:
            RoutingDecision with selected provider and fallbacks.
        """
        available = [r for r in routes if self._is_provider_available(r)]

        if not available:
            # All providers unavailable — use first as last resort
            fallback_id = routes[0].provider_id if routes else ""
            logger.warning(
                f"Balancer: All providers in '{group_name}' unavailable. "
                f"Falling back to '{fallback_id}'."
            )
            return RoutingDecision(
                selected_provider_id=fallback_id,
                strategy=strategy,
                reason="All providers unavailable, using fallback",
                fallback_chain=[],
            )

        async with self._lock:
            selected_id = ""

            if strategy == RoutingStrategy.PRIORITY:
                selected_id = available[0].provider_id

            elif strategy == RoutingStrategy.WEIGHTED:
                selected_id = self._weighted_select(available)

            elif strategy == RoutingStrategy.ROUND_ROBIN:
                idx = self._round_robin_index.get(group_name, 0)
                selected_id = available[idx % len(available)].provider_id
                self._round_robin_index[group_name] = (idx + 1) % len(available)

            else:
                selected_id = available[0].provider_id

            # Track route counts
            self._route_counts[selected_id] = self._route_counts.get(selected_id, 0) + 1

            # Build fallback chain
            fallbacks = [
                r.provider_id for r in available[1:] if r.provider_id != selected_id
            ][:5]  # Limit to 5 fallbacks

            return RoutingDecision(
                selected_provider_id=selected_id,
                strategy=strategy,
                reason=f"'{selected_id}' selected from {len(available)} available providers",
                fallback_chain=fallbacks,
            )

    def _weighted_select(self, routes: list[ProviderRoute]) -> str:
        """Select a provider using weighted random selection."""
        total_weight = sum(r.weight for r in routes)
        if total_weight <= 0:
            return routes[0].provider_id

        rand_val = random.uniform(0, total_weight)
        cumulative = 0.0
        for route in routes:
            cumulative += route.weight
            if rand_val <= cumulative:
                return route.provider_id

        # Fallback (shouldn't reach here)
        return routes[-1].provider_id

    def get_route_stats(self) -> dict[str, int]:
        """Get route usage counts."""
        return dict(self._route_counts)

    def reset_stats(self) -> None:
        self._route_counts.clear()
        self._round_robin_index.clear()