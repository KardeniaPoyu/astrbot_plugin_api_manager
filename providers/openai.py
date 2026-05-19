"""
OpenAI platform balance probe.

Queries: https://api.openai.com/v1/dashboard/billing/subscription
         https://api.openai.com/v1/dashboard/billing/usage
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiohttp

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class OpenAIProbe(BaseProviderProbe):
    probe_type = "openai"
    display_name = "OpenAI"
    url_patterns = ["api.openai.com", "openai.azure.com"]

    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        effective_base = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"

        headers = {"Authorization": f"Bearer {api_key}"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            # 1. Check subscription info
            sub_url = f"{effective_base}/dashboard/billing/subscription"
            try:
                async with session.get(sub_url, headers=headers) as resp:
                    sub_data = await resp.json(content_type=None) if resp.status == 200 else {}
            except Exception as e:
                logger.warning(f"OpenAI probe: subscription check failed: {e}")
                sub_data = {}

            # 2. Check usage for current + past month
            usage_url = f"{effective_base}/dashboard/billing/usage"
            now = datetime.now(timezone.utc)
            # Try current month first, then 100 days back as fallback
            start_date = (now - timedelta(days=100)).strftime("%Y-%m-%d")
            end_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            params = {"start_date": start_date, "end_date": end_date}

            try:
                async with session.get(usage_url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        usage_data = await resp.json(content_type=None)
                    else:
                        # Maybe billing API not accessible (free tier / org account)
                        # Fall back to simple health check via models list
                        async with session.get(
                            f"{effective_base}/models", headers=headers
                        ) as models_resp:
                            if models_resp.status == 200:
                                return BalanceInfo(
                                    remaining=999999.0,
                                    total=999999.0,
                                    unit="Valid (API OK, billing N/A)",
                                    error=None,
                                )
                            else:
                                text = await models_resp.text()
                                return BalanceInfo(
                                    error=f"API Error ({models_resp.status}): {text[:120]}",
                                    remaining=0.0,
                                )
            except Exception as e:
                logger.warning(f"OpenAI probe: usage check failed: {e}")
                return BalanceInfo(
                    error=f"Request failed: {e}",
                    remaining=0.0,
                )

            # Parse usage
            total_used = 0.0
            if isinstance(usage_data, dict):
                total_used = float(usage_data.get("total_usage", 0)) / 100.0

            # Parse subscription hard/soft limits
            hard_limit = 0.0
            soft_limit = 0.0
            if isinstance(sub_data, dict):
                hard_limit = float(sub_data.get("hard_limit_usd", 0))
                soft_limit = float(sub_data.get("soft_limit_usd", 0))

            effective_limit = hard_limit if hard_limit > 0 else (soft_limit if soft_limit > 0 else 999999.0)
            remaining = max(0.0, effective_limit - total_used)

            return BalanceInfo(
                total=effective_limit,
                used=total_used,
                remaining=remaining,
                unit="USD",
                error=None,
            )