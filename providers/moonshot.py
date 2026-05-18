"""
Moonshot (Kimi) platform balance probe.

Queries: https://api.moonshot.ai/v1/users/me/balance
"""
from __future__ import annotations

import logging

import aiohttp

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class MoonshotProbe(BaseProviderProbe):
    probe_type = "moonshot"
    display_name = "Moonshot (Kimi)"
    url_patterns = ["api.moonshot.ai", "moonshot.ai", "kimi.moonshot.cn"]

    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        effective_base = base_url.rstrip("/") if base_url else "https://api.moonshot.ai"
        url = f"{effective_base}/v1/users/me/balance"
        headers = {"Authorization": f"Bearer {api_key}"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url, headers=headers) as resp:
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = {"error": await resp.text()}

                if not isinstance(data, dict):
                    data = {"error": str(data)}

                if resp.status == 200:
                    return BalanceInfo(
                        total=float(data.get("available_balance", 0)),
                        used=0.0,
                        remaining=float(data.get("available_balance", 0)),
                        unit="CNY",
                        error=None,
                    )

                err = data.get("error", {})
                if isinstance(err, dict):
                    return BalanceInfo(
                        error=err.get("message", "Unknown error"),
                        remaining=0.0,
                    )
                return BalanceInfo(
                    error=str(err) or "Unknown error",
                    remaining=0.0,
                )