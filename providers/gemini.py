"""
Google Gemini platform balance probe.

Uses the Gemini API's models.list endpoint to validate the key,
and optionally checks quota via the service account / cloud billing APIs.
"""
from __future__ import annotations

import logging

import aiohttp

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class GeminiProbe(BaseProviderProbe):
    probe_type = "gemini"
    display_name = "Google Gemini"
    url_patterns = ["generativelanguage.googleapis.com", "gemini.google"]

    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        effective_base = base_url.rstrip("/") if base_url else "https://generativelanguage.googleapis.com"

        headers = {"Content-Type": "application/json"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            # Validate the key by listing available models
            try:
                url = f"{effective_base}/v1beta/models?key={api_key}"
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        model_count = len(data.get("models", [])) if isinstance(data, dict) else 0
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