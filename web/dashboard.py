"""
WebUI Dashboard for API Manager.

Provides a rich, interactive dashboard view in AstrBot's WebUI.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger("astrbot.api_mgr")


def register_web_dashboard(context: Any) -> None:
    """Register the WebUI dashboard route.

    This is called from the plugin's initialize() method.
    """
    import json
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse

    async def dashboard_handler(request: Any) -> JSONResponse:
        """Serve the dashboard data as JSON for AstrBot's web panel."""
        try:
            data = {
                "title": "API 管家",
                "version": "1.4.0",
                "tabs": [
                    {"id": "overview", "label": "总览", "icon": "dashboard"},
                    {"id": "providers", "label": "提供商", "icon": "cloud"},
                    {"id": "routes", "label": "路由组", "icon": "alt_route"},
                    {"id": "stats", "label": "统计", "icon": "bar_chart"},
                    {"id": "settings", "label": "设置", "icon": "settings"},
                ],
                "quick_actions": [
                    {"action": "/api balance", "label": "刷新余额", "icon": "refresh"},
                    {"action": "/api group list", "label": "查看路由组", "icon": "list"},
                    {"action": "/api list", "label": "列出所有模型", "icon": "format_list_bulleted"},
                ],
                "supported_providers": [
                    "OpenAI", "Anthropic", "Google Gemini", "Groq",
                    "DeepSeek", "SiliconFlow", "Moonshot/Kimi", "OneAPI/NewAPI", "Aliyun DashScope",
                ],
                "features": [
                    "多平台余额探测",
                    "意图识别自动场景切换",
                    "熔断器故障隔离",
                    "路由统计与负载均衡",
                    "后台定时余额刷新",
                ],
            }
            return JSONResponse(data)
        except Exception as e:
            logger.error(f"API Manager Web Dashboard: Error: {e}", exc_info=True)
            return JSONResponse({"error": str(e)}, status_code=500)

    try:
        context.register_web_api(
            route="/api_manager/dashboard",
            view_handler=dashboard_handler,
            methods=["GET"],
            desc="API Manager WebUI Dashboard",
        )
        logger.info("API Manager WebUI: Dashboard route registered at /api_manager/dashboard")
    except Exception as e:
        logger.warning(f"API Manager WebUI: Failed to register dashboard route: {e}")