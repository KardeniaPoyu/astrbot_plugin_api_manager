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
    @staticmethod
    async def get_balance(provider_type: str, api_key: str, base_url: str = None, model_name: str = None) -> dict:
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
            elif provider_type == "aliyun":
                return await ApiService._query_aliyun(api_key, model_name)
            else:
                return {"error": f"Unsupported provider type: {provider_type}"}
        except Exception as e:
            logger.error(f"Error querying balance for {provider_type}: {e}", exc_info=True)
            return {"error": str(e)}

    @staticmethod
    async def _query_deepseek(api_key: str):
        url = "https://api.deepseek.com/user/balance"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                try:
                    data = await resp.json()
                except:
                    data = {"error": await resp.text()}
                
                if not isinstance(data, dict):
                    data = {"error": str(data)}

                if resp.status == 200:
                    if data.get("is_available"):
                        balance_info = data.get("balance_infos", [{}])[0]
                        return {
                            "total": float(balance_info.get("total_balance", 0)),
                            "used": 0,
                            "remaining": float(balance_info.get("total_balance", 0)),
                            "unit": balance_info.get("currency", "CNY")
                        }
                    else:
                        return {"error": "DeepSeek account not available or balance zero."}
                
                # Handle error dict
                err = data.get("error", {})
                if isinstance(err, dict):
                    return {"error": err.get("message", "Unknown error")}
                return {"error": str(err) or "Unknown error"}

    @staticmethod
    async def _query_aliyun(api_key: str, model_name: str = None):
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # If no model configured, fallback to probing qwen-turbo
        test_model = model_name if model_name else "qwen-turbo"
        
        payload = {
            "model": test_model,
            "messages": [{"role": "user", "content": "1"}],
            "max_tokens": 1
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        return {
                            "total": 999999,
                            "used": 0,
                            "remaining": 999999,
                            "unit": f"Valid ({test_model} OK)"
                        }
                    else:
                        err_msg = "Unknown error"
                        if isinstance(data, dict) and "error" in data:
                            err = data["error"]
                            if isinstance(err, dict):
                                err_msg = err.get("message", "Unknown error")
                            else:
                                err_msg = str(err)
                        
                        # Return 0 remaining to trigger auto-switching
                        return {"error": f"API Error ({resp.status}): {err_msg}", "remaining": 0, "unit": "Error"}
            except Exception as e:
                return {"error": f"Request failed: {str(e)}", "remaining": 0, "unit": "Error"}

    @staticmethod
    async def _query_siliconflow(api_key: str):
        url = "https://api.siliconflow.cn/v1/user/info"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                try:
                    data = await resp.json()
                except:
                    data = {"error": await resp.text()}

                if not isinstance(data, dict):
                    data = {"error": str(data)}

                if resp.status == 200 and (data.get("status") is True or data.get("code") == 20000):
                    data = data.get("data", {})
                    return {
                        "total": float(data.get("totalBalance", 0)),
                        "used": float(data.get("totalBalance", 0)) - float(data.get("balance", 0)),
                        "remaining": float(data.get("balance", 0)),
                        "unit": "CNY"
                    }
                return {"error": data.get("message", data.get("error", "Unknown error"))}

    @staticmethod
    async def _query_moonshot(api_key: str):
        url = "https://api.moonshot.ai/v1/users/me/balance"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                try:
                    data = await resp.json()
                except:
                    data = {"error": await resp.text()}

                if not isinstance(data, dict):
                    data = {"error": str(data)}

                if resp.status == 200:
                    return {
                        "total": float(data.get("available_balance", 0)),
                        "used": 0,
                        "remaining": float(data.get("available_balance", 0)),
                        "unit": "CNY"
                    }
                
                err = data.get("error", {})
                if isinstance(err, dict):
                    return {"error": err.get("message", "Unknown error")}
                return {"error": str(err) or "Unknown error"}

    @staticmethod
    async def _query_oneapi(api_key: str, base_url: str):
        if not base_url:
            return {"error": "Base URL required for OneAPI"}
        
        # Strip /v1 if present for API calls
        base_url = base_url.rstrip('/')
        if base_url.endswith('/v1'):
            base_url = base_url[:-3]
            
        url = f"{base_url}/api/user/info" 
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                try:
                    data = await resp.json()
                except:
                    data = {"error": await resp.text()}

                if resp.status == 200 and isinstance(data, dict):
                    user_data = data.get("data", {})
                    if not isinstance(user_data, dict):
                        return {"error": "Unexpected data format from OneAPI"}
                    # OneAPI balance is usually in 'quota', 1 USD = 500000 quota by default
                    quota = user_data.get("quota", 0)
                    return {
                        "total": quota,
                        "used": user_data.get("used_quota", 0),
                        "remaining": quota,
                        "unit": "Quota"
                    }
                
                # Try v1/user/info as fallback (NewAPI/some OneAPI versions)
                v1_url = f"{base_url}/v1/user/info"
                async with session.get(v1_url, headers=headers) as resp2:
                    if resp2.status == 200:
                        try:
                            data = await resp2.json()
                        except:
                            data = {}
                        
                        if not isinstance(data, dict): data = {}

                        # Some return quota directly in data
                        if "quota" in data:
                            return {"total": data["quota"], "used": 0, "remaining": data["quota"], "unit": "Quota"}
                        if "data" in data and isinstance(data["data"], dict) and "quota" in data["data"]:
                            return {"total": data["data"]["quota"], "used": 0, "remaining": data["data"]["quota"], "unit": "Quota"}
                
                return {"error": f"Failed to query OneAPI (HTTP {resp.status})"}


