"""
Auto-discovery registry for provider probes.

Supports:
- Auto-detection of provider type from base_url, model name, or provider ID.
- Registration of custom probes.
- Fallback chain for unknown providers.
"""
from __future__ import annotations

import logging
from typing import Optional

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")


class ProviderRegistry:
    """Manages registered provider probes and auto-detects provider types."""

    def __init__(self):
        self._probes: dict[str, BaseProviderProbe] = {}
        self._probe_list: list[BaseProviderProbe] = []
        self._overrides: dict[str, str] = {}  # provider_id → probe_type

    def register(self, probe: BaseProviderProbe) -> None:
        """Register a provider probe."""
        probe_type = probe.probe_type.lower()
        if probe_type in self._probes:
            logger.warning(f"ProviderRegistry: Overwriting probe type '{probe_type}'")
        self._probes[probe_type] = probe
        self._probe_list.append(probe)
        logger.info(f"ProviderRegistry: Registered probe '{probe_type}' ({probe.display_name})")

    def register_many(self, probes: list[BaseProviderProbe]) -> None:
        for p in probes:
            self.register(p)

    def get_all_probe_types(self) -> list[str]:
        return sorted(self._probes.keys())

    def set_override(self, provider_id: str, probe_type: str) -> None:
        """Manually set the probe type for a specific provider ID."""
        self._overrides[provider_id] = probe_type.lower()

    def remove_override(self, provider_id: str) -> None:
        self._overrides.pop(provider_id, None)

    def get_override(self, provider_id: str) -> Optional[str]:
        return self._overrides.get(provider_id)

    def detect_probe_type(
        self,
        provider_id: str = "",
        base_url: str = "",
    ) -> str:
        """
        Auto-detect the most appropriate probe type.

        Priority order:
        1. Manual override (self._overrides)
        2. base_url pattern matching
        3. provider_id prefix matching

        Returns probe_type string or "none" if no match.
        """
        # 1. Manual override always wins
        if provider_id and provider_id in self._overrides:
            return self._overrides[provider_id]

        base_url_lower = (base_url or "").lower()

        # 2. URL pattern matching (most reliable)
        for probe in self._probe_list:
            for pattern in probe.url_patterns:
                if pattern and pattern in base_url_lower:
                    return probe.probe_type

        # 3. Provider ID prefix matching (e.g. "openai/gpt-4o" → "openai")
        if provider_id:
            prefix = provider_id.split("/")[0].lower()
            if prefix in self._probes:
                return prefix

            # Special aliases
            alias_map = {
                "kimi": "moonshot",
                "qwen": "aliyun",
                "dashscope": "aliyun",
                "newapi": "oneapi",
                "deepseek": "deepseek",
                "siliconflow": "siliconflow",
            }
            if prefix in alias_map:
                mapped = alias_map[prefix]
                if mapped in self._probes:
                    return mapped

        # 4. Check URL for known gateway patterns
        if base_url_lower:
            gateway_keywords = ["oneapi", "newapi"]
            if any(k in base_url_lower for k in gateway_keywords):
                return "oneapi"

        return "none"

    async def probe(
        self,
        probe_type: str,
        api_key: str,
        base_url: str = "",
        model_name: str = "",
    ) -> BalanceInfo:
        """
        Run a balance/health probe for the given provider type.

        Args:
            probe_type: The probe type identifier (e.g. "openai", "deepseek").
            api_key: API key.
            base_url: Base URL for custom endpoints.
            model_name: Model name for model-aware probes.

        Returns:
            BalanceInfo with results or error details.
        """
        probe = self._probes.get(probe_type.lower())
        if not probe:
            return BalanceInfo(
                error=f"Unsupported probe type: {probe_type}",
                remaining=0.0,
            )

        try:
            import time
            result = await probe.probe(api_key, base_url=base_url, model_name=model_name)
            result.timestamp = time.time()
            return result
        except Exception as e:
            import time
            logger.error(f"ProviderRegistry: Probe '{probe_type}' failed: {e}", exc_info=True)
            return BalanceInfo(
                error=str(e),
                remaining=0.0,
                timestamp=time.time(),
            )

    @property
    def probe_count(self) -> int:
        return len(self._probes)


# Global singleton for the plugin
global_registry = ProviderRegistry()