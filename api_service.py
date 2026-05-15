import aiohttp
import logging

logger = logging.getLogger("astrbot.api_mgr")

class ApiService:
    @staticmethod
    async def get_balance(provider_type: str, api_key: str, base_url: str = None) -> dict:
        """
        Query balance for different providers.
        Returns a dict with 'total', 'used', 'remaining' and 'unit'.
        """
        try:
            if provider_type == "deepseek":
                return await ApiService._query_deepseek(api_key)
            elif provider_type == "siliconflow":
                return await ApiService._query_siliconflow(api_key)
            elif provider_type == "moonshot":
                return await ApiService._query_moonshot(api_key)
            elif provider_type == "oneapi":
                return await ApiService._query_oneapi(api_key, base_url)
            else:
                # Try generic OpenAI-compatible balance if possible (rarely standard)
                return {"error": f"Unsupported provider type: {provider_type}"}
        except Exception as e:
            logger.error(f"Error querying balance for {provider_type}: {e}")
            return {"error": str(e)}

    @staticmethod
    async def _query_deepseek(api_key: str):
        url = "https://api.deepseek.com/user/balance"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("is_available"):
                    balance_info = data.get("balance_infos", [{}])[0]
                    return {
                        "total": float(balance_info.get("total_balance", 0)),
                        "used": 0, # DeepSeek doesn't show used in this endpoint
                        "remaining": float(balance_info.get("total_balance", 0)),
                        "unit": balance_info.get("currency", "CNY")
                    }
                return {"error": data.get("error", "Unknown error")}

    @staticmethod
    async def _query_siliconflow(api_key: str):
        url = "https://api.siliconflow.cn/v1/user/info"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("status"):
                    data = data.get("data", {})
                    return {
                        "total": float(data.get("totalBalance", 0)),
                        "used": float(data.get("totalBalance", 0)) - float(data.get("balance", 0)),
                        "remaining": float(data.get("balance", 0)),
                        "unit": "CNY"
                    }
                return {"error": data.get("message", "Unknown error")}

    @staticmethod
    async def _query_moonshot(api_key: str):
        url = "https://api.moonshot.ai/v1/users/me/balance"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                if resp.status == 200:
                    return {
                        "total": float(data.get("available_balance", 0)), # Simplified
                        "used": 0,
                        "remaining": float(data.get("available_balance", 0)),
                        "unit": "CNY"
                    }
                return {"error": data.get("error", "Unknown error")}

    @staticmethod
    async def _query_oneapi(api_key: str, base_url: str):
        if not base_url:
            return {"error": "Base URL required for OneAPI"}
        # OneAPI usually has /api/user/info for the dashboard, but for API keys it might differ.
        # Often people use /v1/user/info for some OpenAI compatibles.
        url = f"{base_url.rstrip('/')}/api/user/info" 
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    user_data = data.get("data", {})
                    # OneAPI balance is usually in 'quota', 1 USD = 500000 quota by default
                    quota = user_data.get("quota", 0)
                    return {
                        "total": quota,
                        "used": user_data.get("used_quota", 0),
                        "remaining": quota,
                        "unit": "Quota"
                    }
                return {"error": f"HTTP {resp.status}"}
