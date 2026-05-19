"""
Anthropic (Claude) platform balance probe.

Anthropic does not expose a public balance endpoint. This probe performs
a lightweight API validation by listing models or checking key validity.
"""
from __future__ import annotations

import logging

import aiohttp

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class AnthropicProbe(BaseProviderProbe):
    probe_type = "anthropic"
    display_name = "Anthropic (Claude)"
    url_patterns = ["api.anthropic.com", "claude.ai"]

    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        effective_base = base_url.rstrip("/") if base_url else "https://api.anthropic.com"

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            # Anthropic doesn't have a balance endpoint. We validate the key
            # by making a minimal API call to list models.
            try:
                async with session.get(
                    f"{effective_base}/v1/models", headers=headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        model_count = len(data.get("data", [])) if isinstance(data, dict) else 0
                        return BalanceInfo(
                            remaining=999999.0,
                            total=999999.0,
                            unit=f"Valid ({model_count} models)",
                            error=None,
                        )
                    else:
                        try:
                            err_data = await resp.json(content_type=None)
                        except Exception:
                            err_data = {}
                        err_msg = ""
                        if isinstance(err_data, dict):
                            err = err_data.get("error", {})
                            if isinstance(err, dict):
                                err_msg = err.get("message", "Unknown error")
                            else:
                                err_msg = str(err)
                        return BalanceInfo(
                            error=f"API Error ({resp.status}): {err_msg or await resp.text()[:120]}",
                            remaining=0.0,
                        )
            except aiohttp.ClientError as e:
                return BalanceInfo(
                    error=f"Network error: {e}",
                    remaining=0.0,
                )