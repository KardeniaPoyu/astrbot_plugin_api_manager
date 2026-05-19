"""
Aliyun DashScope (Qwen) platform balance probe.

DashScope does not expose a balance endpoint. Validates the key
by making a minimal API call.
"""
from __future__ import annotations

import logging

import aiohttp

from .base import BalanceInfo, BaseProviderProbe

logger = logging.getLogger("astrbot.api_mgr")
_TIMEOUT = aiohttp.ClientTimeout(total=20)


class AliyunProbe(BaseProviderProbe):
    probe_type = "aliyun"
    display_name = "Aliyun DashScope (Qwen)"
    url_patterns = ["dashscope.aliyuncs.com", "aliyuncs.com"]

    async def probe(self, api_key: str, base_url: str = "", model_name: str = "") -> BalanceInfo:
        effective_base = base_url.rstrip("/") if base_url else "https://dashscope.aliyuncs.com"
        url = f"{effective_base}/compatible-mode/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # If model is specified, probe that model; otherwise, default to qwen-turbo
        test_model = model_name if model_name else "qwen-turbo"

        payload = {
            "model": test_model,
            "messages": [{"role": "user", "content": "1"}],
            "max_tokens": 1,
        }

        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {}

                    if resp.status == 200:
                        return BalanceInfo(
                            total=999999.0,
                            used=0.0,
                            remaining=999999.0,
                            unit=f"Valid ({test_model} OK)",
                            error=None,
                        )
                    else:
                        err_msg = "Unknown error"
                        if isinstance(data, dict) and "error" in data:
                            err = data["error"]
                            if isinstance(err, dict):
                                err_msg = err.get("message", "Unknown error")
                            else:
                                err_msg = str(err)

                        return BalanceInfo(
                            error=f"API Error ({resp.status}): {err_msg}",
                            remaining=0.0,
                        )
            except aiohttp.ClientError as e:
                return BalanceInfo(
                    error=f"Request failed: {e}",
                    remaining=0.0,
                )