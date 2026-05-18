"""
OneAPI / NewAPI platform balance probe.

Queries: <base_url>/api/user/info or <base_url>/v1/user/info
"""
from __future__ import annotations

import logging

import aiohttp

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class OneAPIProbe(BaseProviderProbe):
    probe_type = "oneapi"
    display_name = "OneAPI / NewAPI"
    url_patterns = []  # Depends on custom base_url

    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        if not base_url:
            return BalanceInfo(
                error="Base URL required for OneAPI probe",
                remaining=0.0,
            )

        # Normalize base_url
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]

        headers = {"Authorization": f"Bearer {api_key}"}

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            # Try /api/user/info first
            try:
                async with session.get(f"{base}/api/user/info", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if isinstance(data, dict):
                            user_data = data.get("data", {})
                            if isinstance(user_data, dict):
                                quota = user_data.get("quota", 0)
                                return BalanceInfo(
                                    total=float(quota),
                                    used=float(user_data.get("used_quota", 0)),
                                    remaining=float(quota),
                                    unit="Quota",
                                    error=None,
                                )
            except Exception as e:
                logger.debug(f"OneAPI /api/user/info failed: {e}")

            # Fallback: /v1/user/info
            try:
                async with session.get(f"{base}/v1/user/info", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if isinstance(data, dict):
                            # Direct quota
                            if "quota" in data:
                                return BalanceInfo(
                                    total=float(data["quota"]),
                                    used=0.0,
                                    remaining=float(data["quota"]),
                                    unit="Quota",
                                    error=None,
                                )
                            # Nested data.quota
                            d = data.get("data", {})
                            if isinstance(d, dict) and "quota" in d:
                                return BalanceInfo(
                                    total=float(d["quota"]),
                                    used=0.0,
                                    remaining=float(d["quota"]),
                                    unit="Quota",
                                    error=None,
                                )
            except Exception as e:
                logger.debug(f"OneAPI /v1/user/info failed: {e}")

            # Fallback: validate key by listing models
            try:
                async with session.get(f"{base}/v1/models", headers=headers) as resp:
                    if resp.status == 200:
                        return BalanceInfo(
                            remaining=999999.0,
                            total=999999.0,
                            unit="Valid (API OK, quota N/A)",
                            error=None,
                        )
                    else:
                        return BalanceInfo(
                            error=f"API Error ({resp.status})",
                            remaining=0.0,
                        )
            except Exception as e:
                return BalanceInfo(
                    error=f"Network error: {e}",
                    remaining=0.0,
                )