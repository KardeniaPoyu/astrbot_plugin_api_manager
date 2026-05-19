"""
Provider probe abstract base class.

Each provider type implements a probe that queries balance/health info
from the upstream API. Probes are auto-discovered by the registry.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BalanceInfo:
    """Normalized balance/health result for a provider."""
    provider_id: str = ""
    total: float = 0.0
    used: float = 0.0
    remaining: float = 0.0
    unit: str = "CNY"
    error: Optional[str] = None
    extra: dict = field(default_factory=dict)
    timestamp: float = 0.0

    @property
    def is_healthy(self) -> bool:
        return self.error is None

    @property
    def is_exhausted(self) -> bool:
        if self.error:
            return True
        return self.remaining <= 0.0

    def to_dict(self) -> dict:
        return {
            "remaining": self.remaining,
            "total": self.total,
            "used": self.used,
            "unit": self.unit,
            "error": self.error,
            "extra": self.extra,
        }


class BaseProviderProbe(ABC):
    """Abstract interface for a provider balance/health probe."""

    # Unique identifier for this probe type (e.g. "openai", "deepseek").
    probe_type: str = "base"

    # Human-readable display name.
    display_name: str = "Base Provider"

    # List of base_url substrings that auto-match this probe.
    url_patterns: list[str] = []

    @abstractmethod
    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        """Query balance/health from the provider's API.

        Args:
            api_key: The API key.
            base_url: Base URL (may be empty for well-known providers).
            model_name: Model name for model-specific probes.

        Returns:
            BalanceInfo with balance data or error details.
        """
        ...