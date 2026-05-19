"""
Groq platform balance probe.

Groq does not expose a public balance endpoint. Validates the key
by listing available models.
"""
from __future__ import annotations

import logging

import aiohttp

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class GroqProbe(BaseProviderProbe):
    probe_type = "groq"
    display_name = "Groq"
    url_patterns = ["api.groq.com", "groq.com"]

    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        effective_base = base_url.rstrip("/") if base_url else "https://api.groq.com"

        headers = {
            "Authorization": f"Bearer {api_key}",
        }

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            try:
                # Groq uses OpenAI-compatible /v1/models
                async with session.get(
                    f"{effective_base}/openai/v1/models", headers=headers
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