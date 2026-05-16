import asyncio
import logging
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from .api_service import ApiService

logger = logging.getLogger("astrbot.api_mgr")

@register("api_mgr", "KardeniaPoyu", "管理模型提供商及 API Key，自动根据 API 情况调整模型，显示剩余额度。", "1.0.0", "https://github.com/KardeniaPoyu/astrbot_plugin_api_mgr")
class ApiMgrPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.active_group = "default"
        self.groups = {} # group_name -> list of provider_ids
        self.provider_types = {} # provider_id -> type (deepseek, siliconflow, etc.)

    async def initialize(self):
        # Load data from KV store
        self.active_group = await self.get_kv_data("active_group", "default")
        self.groups = await self.get_kv_data("groups", {"default": []})
        self.provider_types = await self.get_kv_data("provider_types", {})
        self.balance_cache = {} # provider_id -> balance_info
        self.min_balance = await self.get_kv_data("min_balance", 0.01)

    def _get_provider_type(self, p):
        p_id = p.provider_config.get("id", "").lower()
        if p_id in self.provider_types:
            return self.provider_types[p_id]
        
        # Access nested config if present
        config = p.provider_config.get("config", {})
        base_url = (p.provider_config.get("base_url") or config.get("base_url") or "").lower()
        
        # Auto-detection
        if "deepseek" in p_id or "deepseek" in base_url:
            return "deepseek"
        if "siliconflow" in p_id or "siliconflow" in base_url:
            return "siliconflow"
        if "moonshot" in p_id or "kimi" in p_id or "moonshot" in base_url:
            return "moonshot"
        if "oneapi" in p_id or "newapi" in p_id:
            return "oneapi"
        
        return "none"

    @filter.command_group("api")
    def api_group(self):
        pass

    @api_group.command("list")
    async def list_providers(self, event: AstrMessageEvent):
        """列出所有已配置的提供商及其 ID"""
        providers = self.context.get_all_providers()
        if not providers:
            yield event.plain_result("未发现任何已配置的提供商。")
            return
        
        msg = "当前已配置的提供商:\n"
        for i, p in enumerate(providers):
            p_id = p.provider_config.get("id", "Unknown")
            p_type = p.provider_config.get("type", "Unknown")
            detected_type = self._get_provider_type(p)
            balance_str = ""
            if p_id in self.balance_cache:
                b = self.balance_cache[p_id]
                balance_str = f" | 余额: {b.get('remaining', '?')} {b.get('unit', '')}"
            msg += f"{i+1}. ID: {p_id} | 类型: {p_type} | 余额查询: {detected_type}{balance_str}\n"
        
        yield event.plain_result(msg)

    @api_group.command("set_type")
    async def set_provider_type(self, event: AstrMessageEvent, provider_id: str, provider_type: str):
        """设置提供商的余额查询类型 (deepseek, siliconflow, moonshot, oneapi, none, auto)"""
        valid_types = ["deepseek", "siliconflow", "moonshot", "oneapi", "none", "auto"]
        provider_type = provider_type.lower()
        if provider_type not in valid_types:
            yield event.plain_result(f"无效的类型。支持: {', '.join(valid_types)}")
            return
        
        # Support numeric ID if needed
        providers = self.context.get_all_providers()
        if provider_id.isdigit():
            idx = int(provider_id) - 1
            if 0 <= idx < len(providers):
                provider_id = providers[idx].provider_config.get("id")
            else:
                yield event.plain_result(f"序号 {provider_id} 超出范围。")
                return

        if provider_type == "auto":
            if provider_id in self.provider_types:
                del self.provider_types[provider_id]
        else:
            self.provider_types[provider_id] = provider_type
            
        await self.put_kv_data("provider_types", self.provider_types)
        yield event.plain_result(f"已将 {provider_id} 的余额查询类型设置为 {provider_type}")

    @api_group.command("min_balance")
    async def set_min_balance(self, event: AstrMessageEvent, min_bal: float):
        """设置自动切换的最小余额阈值"""
        self.min_balance = min_bal
        await self.put_kv_data("min_balance", self.min_balance)
        yield event.plain_result(f"最小余额阈值已设置为 {min_bal}")

    @api_group.command("balance")
    async def check_balance(self, event: AstrMessageEvent, provider_id: str = None):
        """查询余额并更新缓存。"""
        providers = self.context.get_all_providers()
        
        target_providers = []
        if provider_id:
            # Support numeric ID
            if provider_id.isdigit():
                idx = int(provider_id) - 1
                if 0 <= idx < len(providers):
                    target_providers.append(providers[idx])
                else:
                    yield event.plain_result(f"序号 {provider_id} 超出范围。")
                    return
            else:
                p = self.context.get_provider_by_id(provider_id)
                if p: target_providers.append(p)
                else:
                    yield event.plain_result(f"未找到 ID 为 {provider_id} 的提供商。")
                    return
        else:
            target_providers = [p for p in providers if self._get_provider_type(p) != "none"]

        if not target_providers:
            yield event.plain_result("没有可查询余额的提供商。请先使用 /api set_type 设置类型。")
            return

        yield event.plain_result("正在查询余额并刷新缓存...")
        
        results = []
        for p in target_providers:
            p_id = p.provider_config.get("id")
            p_type = self._get_provider_type(p)
            if p_type == "none": continue
            
            config = p.provider_config.get("config", {})
            api_key = p.provider_config.get("api_key") or config.get("api_key")
            base_url = p.provider_config.get("base_url") or config.get("base_url")
            
            if not api_key:
                results.append(f"❌ {p_id}: 未找到 API Key")
                continue
                
            balance = await ApiService.get_balance(p_type, api_key, base_url)
            if "error" in balance:
                results.append(f"❌ {p_id}: 查询失败 ({balance['error']})")
            else:
                self.balance_cache[p_id] = balance
                results.append(f"✅ {p_id}: 剩余 {balance['remaining']} {balance['unit']}")
        
        yield event.plain_result("\n".join(results))


    @api_group.command("group")
    async def manage_groups(self, event: AstrMessageEvent, action: str, group_name: str = None, *provider_ids: str):
        """管理路由组。action: add, remove, delete, list, use"""
        if action == "list":
            msg = "当前路由组:\n"
            for name, p_ids in self.groups.items():
                active_mark = " (当前激活)" if name == self.active_group else ""
                msg += f"- {name}{active_mark}: {', '.join(p_ids)}\n"
            yield event.plain_result(msg)
            return

        if not group_name:
            yield event.plain_result("请提供路由组名称。")
            return

        if action == "use":
            if group_name in self.groups:
                self.active_group = group_name
                await self.put_kv_data("active_group", self.active_group)
                yield event.plain_result(f"已切换到路由组: {group_name}")
            else:
                yield event.plain_result(f"路由组 {group_name} 不存在。")
            return

        if action == "add":
            if group_name not in self.groups:
                self.groups[group_name] = []
            for p_id in provider_ids:
                if p_id not in self.groups[group_name]:
                    self.groups[group_name].append(p_id)
            await self.put_kv_data("groups", self.groups)
            yield event.plain_result(f"已将 {', '.join(provider_ids)} 添加到组 {group_name}")
        
        elif action == "remove":
            if group_name in self.groups:
                for p_id in provider_ids:
                    if p_id in self.groups[group_name]:
                        self.groups[group_name].remove(p_id)
                await self.put_kv_data("groups", self.groups)
                yield event.plain_result(f"已从组 {group_name} 移除 {', '.join(provider_ids)}")
        
        elif action == "delete":
            if group_name in self.groups:
                del self.groups[group_name]
                if self.active_group == group_name:
                    self.active_group = "default"
                await self.put_kv_data("groups", self.groups)
                await self.put_kv_data("active_group", self.active_group)
                yield event.plain_result(f"已删除组 {group_name}")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def on_message(self, event: AstrMessageEvent):
        """拦截消息并应用路由策略"""
        if self.active_group == "default" and not self.groups.get("default"):
            return

        group_providers = self.groups.get(self.active_group, [])
        if not group_providers:
            return

        if event.message_str.startswith("/api"):
            return

        # 动态选择：在组内寻找余额充足的第一个提供商
        selected_provider_id = None
        for p_id in group_providers:
            if p_id in self.balance_cache:
                rem = self.balance_cache[p_id].get("remaining", 0)
                if rem < self.min_balance:
                    logger.warning(f"API Manager: Provider {p_id} balance low ({rem}), skipping.")
                    continue
            selected_provider_id = p_id
            break
        
        if not selected_provider_id:
            selected_provider_id = group_providers[0] # Fallback to first if all low

        logger.debug(f"API Manager: Routing session {event.unified_msg_origin} to {selected_provider_id}")
        event.set_extra("selected_provider", selected_provider_id)
        
        # 可选：配置 fallback 链
        fallbacks = [p for p in group_providers if p != selected_provider_id]
        if fallbacks:
            # Note: AstrBot core must support setting fallbacks via extra
            # If not, this might need a core PR or different approach
            event.set_extra("fallback_chat_models", fallbacks)

