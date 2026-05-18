"""
SiliconFlow platform balance probe.

Queries: https://api.siliconflow.cn/v1/user/info
"""
from __future__ import annotations

import logging

import aiohttp

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class SiliconFlowProbe(BaseProviderProbe):
    probe_type = "siliconflow"
    display_name = "SiliconFlow"
    url_patterns = ["api.siliconflow.cn", "siliconflow.cn"]

    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        effective_base = base_url.rstrip("/") if base_url else "https://api.siliconflow.cn"
        url = f"{effective_base}/v1/user/info"
        headers = {"Authorization": f"Bearer {api_key}"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url, headers=headers) as resp:
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = {"error": await resp.text()}

                if not isinstance(data, dict):
                    data = {"error": str(data)}

                if resp.status == 200 and (data.get("status") is True or data.get("code") == 20000):
                    d = data.get("data", {})
                    if not isinstance(d, dict):
                        d = {}
                    return BalanceInfo(
                        total=float(d.get("totalBalance", 0)),
                        used=float(d.get("totalBalance", 0)) - float(d.get("balance", 0)),
                        remaining=float(d.get("balance", 0)),
                        unit="CNY",
                        error=None,
                    )
                return BalanceInfo(
                    error=data.get("message", data.get("error", "Unknown error")),
                    remaining=0.0,
                )