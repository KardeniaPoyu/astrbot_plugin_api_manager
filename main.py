import asyncio
import logging
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from .api_service import ApiService

logger = logging.getLogger("astrbot.api_mgr")

@register("api_mgr", "KardeniaPoyu", "专业级 API 管理插件：支持多渠道余额查询、意图识别场景自动切换、负载均衡及自动故障迁移。", "1.1.0", "https://github.com/KardeniaPoyu/astrbot_plugin_api_manager")
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
        self.usage_cache = await self.get_kv_data("usage_cache", {})

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
        if "aliyun" in p_id or "dashscope" in p_id or "dashscope" in base_url or "qwen" in p_id:
            return "aliyun"
        
        return "none"

    @filter.command_group("api")
    def api_group(self):
        pass

    @api_group.command("list")
    async def list_providers(self, event: AstrMessageEvent):
        """列出所有已配置的提供商及其 ID 和状态"""
        providers = list(self.context.get_all_providers())
        if not providers:
            yield event.plain_result("未发现任何已配置的提供商。")
            return
        
        provider_using = self.context.get_using_provider(umo=event.unified_msg_origin)
        msg = "当前已配置的提供商状态:\n"
        for i, p in enumerate(providers):
            p_id = p.provider_config.get("id", "Unknown")
            config = p.provider_config.get("config", {})
            model = config.get("model") or p.provider_config.get("model", "未知")
            detected_type = self._get_provider_type(p)
            
            balance_str = ""
            if p_id in self.balance_cache:
                b = self.balance_cache[p_id]
                if b.get("error"):
                    balance_str = f" | 余额状态: ❌ {b['error']}"
                else:
                    balance_str = f" | 余额状态: {b.get('remaining', '?')} {b.get('unit', '')}"
                    
            usage = self.usage_cache.get(p_id, 0)
            
            active_mark = ""
            if provider_using and provider_using.meta().id == p_id:
                active_mark = " 👈 (当前)"
                
            msg += f"{i+1}. {p_id} ({model}){active_mark}\n   ↳ 探针类型: {detected_type}{balance_str} | 成功路由次数: {usage}\n"
        
        yield event.plain_result(msg)

    @api_group.command("set_type")
    async def set_provider_type(self, event: AstrMessageEvent, provider_id: str, provider_type: str):
        """设置提供商的余额查询类型 (deepseek, siliconflow, moonshot, oneapi, aliyun, none, auto)"""
        valid_types = ["deepseek", "siliconflow", "moonshot", "oneapi", "aliyun", "none", "auto"]
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
            model_name = config.get("model") or p.provider_config.get("model")
            
            if not api_key:
                results.append(f"❌ {p_id}: 未找到 API Key")
                continue
                
            balance = await ApiService.get_balance(p_type, api_key, base_url, model_name)
            if "error" in balance:
                results.append(f"❌ {p_id}: 查询失败 ({balance['error']})")
                if "remaining" in balance:
                    self.balance_cache[p_id] = balance # Force 0 balance into cache for auto-routing
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
            yield event.plain_result(f"已将 {', '.join(provider_ids)} 追加到组 {group_name}")
            
        elif action == "set":
            # 覆盖写入，用于精确设置优先级（排在前面的优先级高）
            self.groups[group_name] = list(provider_ids)
            await self.put_kv_data("groups", self.groups)
            yield event.plain_result(f"已重置组 {group_name}，当前优先级排序为: {', '.join(provider_ids)}")
        
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

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, request: "ProviderRequest"):
        """在请求前劫持 Provider，实现运行时错误自动学习"""
        provider = self.context.get_using_provider(umo=event.unified_msg_origin)
        if not provider:
            return
        
        p_id = provider.provider_config.get("id")
        if not p_id:
            return

        # 只对处于我们管理下的 Provider 进行动态监控
        all_managed_ids = set()
        for g in self.groups.values():
            all_managed_ids.update(g)
        
        if p_id not in all_managed_ids:
            return

        # 装饰 text_chat 和 text_chat_stream 以捕获异常
        if not hasattr(provider, "_api_mgr_wrapped"):
            original_text_chat = provider.text_chat
            original_text_chat_stream = provider.text_chat_stream

            async def wrapped_text_chat(*args, **kwargs):
                try:
                    return await original_text_chat(*args, **kwargs)
                except Exception as e:
                    await self._handle_runtime_error(p_id, e)
                    raise e

            async def wrapped_text_chat_stream(*args, **kwargs):
                try:
                    async for resp in original_text_chat_stream(*args, **kwargs):
                        yield resp
                except Exception as e:
                    await self._handle_runtime_error(p_id, e)
                    raise e

            provider.text_chat = wrapped_text_chat
            provider.text_chat_stream = wrapped_text_chat_stream
            provider._api_mgr_wrapped = True
            logger.debug(f"API Manager: Wrapped provider {p_id} for runtime error monitoring.")

    async def _handle_runtime_error(self, p_id: str, e: Exception):
        """处理运行时捕获到的异常，更新余额缓存"""
        err_str = str(e)
        # 识别典型的额度耗尽、模型错误或权限错误 (400, 401, 403, 429)
        if any(k in err_str for k in ["400", "401", "403", "429", "quota", "balance", "insufficient", "model names"]):
            logger.warning(f"API Manager: Detected permanent/quota error for {p_id}: {err_str}")
            self.balance_cache[p_id] = {
                "remaining": 0, 
                "status": f"❌ Runtime Error: {err_str[:60]}...",
                "last_check": __import__("time").time()
            }
            await self.put_kv_data("balance_cache", self.balance_cache)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def on_message(self, event: AstrMessageEvent):
        """拦截消息并应用路由策略"""
        if event.message_str.startswith("/api"):
            return
            
        # ---------- 自动场景切换 (Auto Scene Routing) ----------
        msg_text = event.message_str
        group_name = self.active_group
        scene_switch_reason = None
        
        # 仅当用户同时配置了 'daily' 和 'reasoning' 组时启用智能切换
        if "daily" in self.groups and "reasoning" in self.groups:
            reasoning_keywords = ["代码", "编程", "脚本", "推导", "分析", "写一个", "实现", "算法", "bug", "报错", "为什么", "code", "python", "javascript", "java", "c++", "数学", "逻辑"]
            
            # 简单启发式：包含关键词，或者内容较长，归为需要推理
            if any(k in msg_text.lower() for k in reasoning_keywords) or len(msg_text) >= 150:
                group_name = "reasoning"
                if self.active_group != "reasoning":
                    scene_switch_reason = "检测到复杂任务/代码/长文本"
            else:
                group_name = "daily"
                if self.active_group != "daily":
                    scene_switch_reason = "检测到日常闲聊"
        # -------------------------------------------------------

        if group_name not in self.groups or not self.groups[group_name]:
            return

        group_providers = self.groups[group_name]

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
        
        # 记录路由次数
        self.usage_cache[selected_provider_id] = self.usage_cache.get(selected_provider_id, 0) + 1
        await self.put_kv_data("usage_cache", self.usage_cache)
        
        # 正式持久化切换（参考 /provider 的底层实现，并且仅当真正发生切换时才执行，并通知用户）
        current_provider = self.context.get_using_provider(umo=event.unified_msg_origin)
        if current_provider and current_provider.meta().id != selected_provider_id:
            try:
                from astrbot.core.provider.entities import ProviderType
                await self.context.provider_manager.set_provider(
                    provider_id=selected_provider_id,
                    provider_type=ProviderType.CHAT_COMPLETION,
                    umo=event.unified_msg_origin
                )
                
                # 根据触发条件动态给出友好的自动切换提示
                if scene_switch_reason:
                    yield event.plain_result(f"🧠 [智能场景切换] {scene_switch_reason}，已自动为您分配最合适的模型组 ({group_name}): {selected_provider_id}")
                else:
                    yield event.plain_result(f"♻️ [API 自动路由] 当前提供商 ({current_provider.meta().id}) 额度不足或不可用，已自动为您无缝切换至备用提供商: {selected_provider_id}")
            except Exception as e:
                logger.error(f"API Manager: Failed to set provider via ProviderManager: {e}")
        
        # 可选：配置 fallback 链
        fallbacks = [p for p in group_providers if p != selected_provider_id]
        if fallbacks:
            # Note: AstrBot core must support setting fallbacks via extra
            # If not, this might need a core PR or different approach
            event.set_extra("fallback_chat_models", fallbacks)

