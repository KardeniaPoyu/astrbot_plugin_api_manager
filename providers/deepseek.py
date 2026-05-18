"""
DeepSeek platform balance probe.

Queries: https://api.deepseek.com/user/balance
"""
from __future__ import annotations

import logging

import aiohttp

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class DeepSeekProbe(BaseProviderProbe):
    probe_type = "deepseek"
    display_name = "DeepSeek"
    url_patterns = ["api.deepseek.com", "deepseek.com"]

    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        effective_base = base_url.rstrip("/") if base_url else "https://api.deepseek.com"
        url = f"{effective_base}/user/balance"
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
                    if data.get("is_available"):
                        balance_info = data.get("balance_infos", [{}])[0]
                        return BalanceInfo(
                            total=float(balance_info.get("total_balance", 0)),
                            used=0.0,
                            remaining=float(balance_info.get("total_balance", 0)),
                            unit=balance_info.get("currency", "CNY"),
                            error=None,
                        )
                    else:
                        return BalanceInfo(
                            error="DeepSeek account not available or balance zero.",
                            remaining=0.0,
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