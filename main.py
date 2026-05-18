"""
AstrBot API Manager Plugin - Enterprise Edition.

Features:
- Provider balance/health probes for 9+ platforms
- Weighted scene detection for intelligent routing
- Circuit breaker for fault isolation
- SQLite-based route statistics
- Periodic background balance checks
- WebUI dashboard
"""
from __future__ import annotations

import time
import logging
from typing import TYPE_CHECKING, Any

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register

if TYPE_CHECKING:
    pass

# ── Plugin imports ──────────────────────────────────────────────────

from providers.base import BalanceInfo
from providers.registry import ProviderRegistry, global_registry
from providers.deepseek import DeepSeekProbe
from providers.siliconflow import SiliconFlowProbe
from providers.moonshot import MoonshotProbe
from providers.oneapi import OneAPIProbe
from providers.aliyun import AliyunProbe
from providers.openai import OpenAIProbe
from providers.anthropic import AnthropicProbe
from providers.gemini import GeminiProbe
from providers.groq import GroqProbe

from router.scene_detector import SceneDetector, DetectionResult
from router.circuit_breaker import (
    CircuitBreakerRegistry,
    STATE_CLOSED,
    STATE_OPEN,
    STATE_HALF_OPEN,
)
from router.balancer import RoutingBalancer, RoutingStrategy, ProviderRoute

from storage.stats_store import StatsStore

from monitor.periodic_check import PeriodicBalanceChecker

logger = logging.getLogger("astrbot.api_mgr")

# ── Constants ───────────────────────────────────────────────────────

# Error patterns indicating permanent/quota failure
QUOTA_ERROR_PATTERNS = [
    "400", "401", "403", "429",
    "quota", "balance", "insufficient",
    "model names", "reached the limit",
    "switch to a paid model", "free tier",
    "RateLimitError", "AuthenticationError",
]


@register(
    "api_mgr",
    "KardeniaPoyu",
    "专业级 API 管理插件：支持多渠道余额查询、意图识别场景自动切换、负载均衡及自动故障迁移。",
    "1.4.0",
    "https://github.com/KardeniaPoyu/astrbot_plugin_api_manager"
)
class ApiMgrPlugin(Star):
    """AstrBot API Manager Plugin - Main entry point."""

    def __init__(self, context: Context):
        super().__init__(context)

        # Core components
        self._registry = ProviderRegistry()
        self._scene_detector = SceneDetector()
        self._cb_registry = CircuitBreakerRegistry()
        self._balancer = RoutingBalancer(circuit_breaker_registry=self._cb_registry)
        self._stats = StatsStore()
        self._periodic_checker = PeriodicBalanceChecker()

        # Persistent state
        self.active_group = "default"
        self.groups: dict[str, list[str]] = {}
        self.provider_types: dict[str, str] = {}
        self.balance_cache: dict[str, dict] = {}
        self.usage_cache: dict[str, int] = {}
        self.min_balance = 0.01
        self.auto_scene_enabled = True
        self.periodic_check_interval = 3600.0

    # ── Lifecycle ────────────────────────────────────────────────────

    async def initialize(self):
        """Load all persistent state and start background tasks."""
        logger.info("API Manager: Initializing...")

        # Load persisted state from KV store
        self.active_group = await self.get_kv_data("active_group", "default")
        self.groups = await self.get_kv_data("groups", {"default": []})
        self.provider_types = await self.get_kv_data("provider_types", {})
        self.balance_cache = await self.get_kv_data("balance_cache", {})
        self.min_balance = await self.get_kv_data("min_balance", 0.01)
        self.usage_cache = await self.get_kv_data("usage_cache", {})
        self.auto_scene_enabled = await self.get_kv_data("auto_scene_enabled", True)
        self.periodic_check_interval = await self.get_kv_data("periodic_check_interval", 3600.0)

        # Register all provider probes
        self._register_probes()

        # Apply manual overrides
        for p_id, p_type in self.provider_types.items():
            self._registry.set_override(p_id, p_type)

        # Start periodic balance checker (if interval > 0)
        if self.periodic_check_interval > 0:
            await self._start_periodic_checker()

        logger.info(
            f"API Manager: Ready. "
            f"Groups: {list(self.groups.keys())}, "
            f"Active: {self.active_group}, "
            f"Probes: {self._registry.probe_count}"
        )

    def _register_probes(self):
        """Register all built-in provider probes."""
        self._registry.register_many([
            DeepSeekProbe(),
            SiliconFlowProbe(),
            MoonshotProbe(),
            OneAPIProbe(),
            AliyunProbe(),
            OpenAIProbe(),
            AnthropicProbe(),
            GeminiProbe(),
            GroqProbe(),
        ])
        logger.info(f"API Manager: Registered {self._registry.probe_count} provider probes")

    async def _start_periodic_checker(self):
        """Start the periodic balance checker."""
        providers = self._get_provider_configs()
        if not providers:
            logger.info("API Manager: No providers to monitor, skipping periodic checker")
            return

        async def on_result(p_id: str, info: dict):
            self.balance_cache[p_id] = info
            try:
                await self.put_kv_data("balance_cache", self.balance_cache)
            except Exception as e:
                logger.warning(f"API Manager: Failed to persist balance_cache: {e}")

        self._periodic_checker._on_result = on_result
        await self._periodic_checker.start(
            probe_fn=self._probe_provider,
            providers=providers,
        )
        self._periodic_checker._interval = self.periodic_check_interval

    def _get_provider_configs(self) -> list[dict]:
        """Extract provider configs from AstrBot's provider manager."""
        providers = []
        try:
            for p in self.context.get_all_providers():
                cfg = p.provider_config
                p_id = cfg.get("id", "")
                config = cfg.get("config", {})
                api_key = None

                try:
                    api_key = p.get_current_key()
                except Exception:
                    pass

                if not api_key:
                    keys = cfg.get("key") or config.get("key") or []
                    if isinstance(keys, list) and keys:
                        api_key = keys[0]
                    elif isinstance(keys, str):
                        api_key = keys

                base_url = cfg.get("base_url") or config.get("base_url") or ""
                model_name = config.get("model") or cfg.get("model") or ""

                providers.append({
                    "id": p_id,
                    "type": self._registry.detect_probe_type(p_id, base_url),
                    "api_key": api_key or "",
                    "base_url": base_url,
                    "model": model_name,
                })
        except Exception as e:
            logger.error(f"API Manager: Failed to get provider configs: {e}")

        return providers

    async def _probe_provider(
        self,
        probe_type: str,
        api_key: str,
        base_url: str = "",
        model_name: str = "",
    ) -> BalanceInfo:
        """Probe a provider's balance/health."""
        return await self._registry.probe(probe_type, api_key, base_url, model_name)

    # ── Utility ───────────────────────────────────────────────────────

    def _is_balance_sufficient(self, p_id: str) -> bool:
        """Check if a provider has sufficient balance."""
        if p_id not in self.balance_cache:
            return True  # No data = optimistically allow
        info = self.balance_cache[p_id]
        if info.get("error"):
            return False
        try:
            rem = float(info.get("remaining", 0))
            return rem >= self.min_balance
        except (TypeError, ValueError):
            return True

    def _get_provider_display_type(self, p) -> str:
        """Get the display type for a provider."""
        p_id = p.provider_config.get("id", "")
        if p_id in self.provider_types:
            return self.provider_types[p_id]
        config = p.provider_config.get("config", {})
        base_url = (p.provider_config.get("base_url") or config.get("base_url") or "")
        return self._registry.detect_probe_type(p_id, base_url)

    # ── Commands ──────────────────────────────────────────────────────

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

        try:
            provider_using = self.context.get_using_provider(umo=event.unified_msg_origin)
        except Exception:
            provider_using = None

        # Get circuit breaker stats
        cb_stats = self._cb_registry.get_all()

        msg = f"📋 当前已配置的提供商状态 (共 {len(providers)} 个):\n"
        msg += "─" * 40 + "\n"

        for i, p in enumerate(providers):
            p_id = p.provider_config.get("id", "Unknown")
            config = p.provider_config.get("config", {})
            model = config.get("model") or p.provider_config.get("model", "未知")
            detected_type = self._get_provider_display_type(p)

            # Balance info
            balance_str = ""
            if p_id in self.balance_cache:
                b = self.balance_cache[p_id]
                if b.get("error"):
                    balance_str = f" | ❌ {b['error'][:30]}"
                else:
                    balance_str = f" | 💰 {b.get('remaining', '?')} {b.get('unit', '')}"

            # Usage count
            usage = self.usage_cache.get(p_id, 0)

            # Circuit breaker state
            cb = cb_stats.get(p_id)
            cb_str = ""
            if cb:
                if cb.state == "OPEN":
                    cb_str = " | 🔴 熔断"
                elif cb.state == "HALF_OPEN":
                    cb_str = " | 🟡 探测中"

            # Active marker
            active_mark = ""
            try:
                if provider_using and provider_using.meta().id == p_id:
                    active_mark = " 👈 (当前)"
            except Exception:
                pass

            msg += f"{i+1}. **{p_id}** ({model}){active_mark}\n"
            msg += f"   ↳ 探针: `{detected_type}`{balance_str} | 路由: {usage}次{cb_str}\n"

        msg += "─" * 40 + "\n"
        msg += f"当前激活组: **{self.active_group}**\n"
        msg += "使用 `/api group list` 查看路由组配置"

        yield event.plain_result(msg)

    @api_group.command("balance")
    async def check_balance(self, event: AstrMessageEvent, provider_id: str = None):
        """查询余额并更新缓存。"""
        providers = list(self.context.get_all_providers())

        target_providers = []
        if provider_id:
            if provider_id.isdigit():
                idx = int(provider_id) - 1
                if 0 <= idx < len(providers):
                    target_providers.append(providers[idx])
                else:
                    yield event.plain_result(f"序号 {provider_id} 超出范围。")
                    return
            else:
                p = self.context.get_provider_by_id(provider_id)
                if p:
                    target_providers.append(p)
                else:
                    yield event.plain_result(f"未找到 ID 为 {provider_id} 的提供商。")
                    return
        else:
            target_providers = [
                p for p in providers
                if self._get_provider_display_type(p) != "none"
            ]

        if not target_providers:
            yield event.plain_result("没有可查询余额的提供商。请先使用 /api set_type 设置类型。")
            return

        yield event.plain_result(f"🔍 正在查询 {len(target_providers)} 个提供商的余额...")

        results = []
        for p in target_providers:
            p_id = p.provider_config.get("id")
            p_type = self._get_provider_display_type(p)
            if p_type == "none":
                continue

            config = p.provider_config.get("config", {})
            api_key = None
            try:
                api_key = p.get_current_key()
            except Exception:
                pass
            if not api_key:
                keys = p.provider_config.get("key") or config.get("key") or []
                if isinstance(keys, list) and keys:
                    api_key = keys[0]
                elif isinstance(keys, str):
                    api_key = keys

            base_url = p.provider_config.get("base_url") or config.get("base_url")
            model_name = config.get("model") or p.provider_config.get("model")

            if not api_key:
                results.append(f"❌ {p_id}: 未找到 API Key")
                continue

            result = await self._probe_provider(p_type, api_key, base_url, model_name)
            if result.error:
                results.append(f"❌ {p_id}: {result.error}")
                self.balance_cache[p_id] = {"remaining": 0, "error": result.error}
            else:
                self.balance_cache[p_id] = result.to_dict()
                results.append(f"✅ {p_id}: 剩余 {result.remaining} {result.unit}")

        await self.put_kv_data("balance_cache", self.balance_cache)
        yield event.plain_result("\n".join(results))

    @api_group.command("set_type")
    async def set_provider_type(self, event: AstrMessageEvent, provider_id: str, provider_type: str):
        """设置提供商的余额查询类型"""
        valid_types = self._registry.get_all_probe_types() + ["none", "auto"]
        provider_type = provider_type.lower()
        if provider_type not in valid_types:
            yield event.plain_result(f"无效的类型。支持: {', '.join(valid_types)}")
            return

        providers = list(self.context.get_all_providers())
        if provider_id.isdigit():
            idx = int(provider_id) - 1
            if 0 <= idx < len(providers):
                provider_id = providers[idx].provider_config.get("id", provider_id)
            else:
                yield event.plain_result(f"序号 {provider_id} 超出范围。")
                return

        if provider_type == "auto":
            self.provider_types.pop(provider_id, None)
            self._registry.remove_override(provider_id)
        else:
            self.provider_types[provider_id] = provider_type
            self._registry.set_override(provider_id, provider_type)

        await self.put_kv_data("provider_types", self.provider_types)
        yield event.plain_result(f"✅ 已将 {provider_id} 的余额查询类型设置为 {provider_type}")

    @api_group.command("min_balance")
    async def set_min_balance(self, event: AstrMessageEvent, min_bal: float):
        """设置自动切换的最小余额阈值"""
        self.min_balance = min_bal
        await self.put_kv_data("min_balance", self.min_balance)
        yield event.plain_result(f"✅ 最小余额阈值已设置为 {min_bal}")

    @api_group.command("auto_scene")
    async def toggle_auto_scene(self, event: AstrMessageEvent, enabled: str = "true"):
        """开启/关闭自动场景切换"""
        self.auto_scene_enabled = enabled.lower() in ("true", "1", "on", "yes")
        await self.put_kv_data("auto_scene_enabled", self.auto_scene_enabled)
        status = "已开启" if self.auto_scene_enabled else "已关闭"
        yield event.plain_result(f"✅ 自动场景切换{status}")

    @api_group.command("stats")
    async def show_stats(self, event: AstrMessageEvent):
        """显示路由统计信息"""
        stats = self._stats.get_provider_stats()
        if not stats:
            yield event.plain_result("暂无路由统计数据。")
            return

        msg = "📊 路由统计 (最近 7 天):\n"
        msg += "─" * 40 + "\n"
        for s in stats[:15]:
            status = "✅" if s.error_rate < 0.1 else ("⚠️" if s.error_rate < 0.3 else "❌")
            msg += f"{status} {s.provider_id}: {s.total_requests}次, 错误率 {s.error_rate:.1%}\n"

        msg += "─" * 40 + "\n"
        msg += f"使用 `/api stats reset` 重置统计"

        yield event.plain_result(msg)

    @api_group.command("cb")
    async def circuit_breaker_cmd(self, event: AstrMessageEvent, action: str, provider_id: str = None):
        """熔断器管理: cb list | cb reset <id> | cb half_open <id>"""
        if action == "list":
            stats = self._cb_registry.get_all()
            if not stats:
                yield event.plain_result("暂无熔断器数据。")
                return
            msg = "🔴 熔断器状态:\n"
            for p_id, s in stats.items():
                state_icon = {"CLOSED": "🟢", "OPEN": "🔴", "HALF_OPEN": "🟡"}.get(s.state, "⚪")
                msg += f"{state_icon} {p_id}: {s.state} (失败: {s.total_failures})\n"
            yield event.plain_result(msg)

        elif action == "reset":
            if not provider_id:
                yield event.plain_result("请提供提供商 ID。")
                return
            cb = self._cb_registry.get(provider_id)
            cb.reset()
            yield event.plain_result(f"✅ 已重置 {provider_id} 的熔断器")

        elif action == "half_open":
            if not provider_id:
                yield event.plain_result("请提供提供商 ID。")
                return
            cb = self._cb_registry.get(provider_id)
            cb.half_open()
            yield event.plain_result(f"✅ 已将 {provider_id} 的熔断器设为 HALF_OPEN")

        else:
            yield event.plain_result("用法: /api cb list | reset <id> | half_open <id>")

    @api_group.command("group")
    async def manage_groups(self, event: AstrMessageEvent, action: str, group_name: str = None, *provider_ids: str):
        """管理路由组。action: add, set, remove, delete, list, use"""
        if action == "list":
            if not self.groups:
                yield event.plain_result("尚未配置任何路由组。")
                return
            msg = "📁 当前路由组:\n"
            msg += "─" * 40 + "\n"
            for name, p_ids in self.groups.items():
                active_mark = " ⭐ (当前激活)" if name == self.active_group else ""
                members = ', '.join(p_ids) if p_ids else "(空)"
                msg += f"• **{name}**{active_mark}: {members}\n"
            yield event.plain_result(msg)
            return

        if not group_name:
            yield event.plain_result("请提供路由组名称。")
            return

        if action == "use":
            if group_name in self.groups:
                self.active_group = group_name
                await self.put_kv_data("active_group", self.active_group)
                yield event.plain_result(f"✅ 已切换到路由组: {group_name}")
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
            yield event.plain_result(f"✅ 已将 {', '.join(provider_ids)} 追加到组 {group_name}")

        elif action == "set":
            self.groups[group_name] = list(provider_ids)
            await self.put_kv_data("groups", self.groups)
            yield event.plain_result(f"✅ 已重置组 {group_name}，当前优先级排序为: {', '.join(provider_ids)}")

        elif action == "remove":
            if group_name in self.groups:
                for p_id in provider_ids:
                    if p_id in self.groups[group_name]:
                        self.groups[group_name].remove(p_id)
                await self.put_kv_data("groups", self.groups)
                yield event.plain_result(f"✅ 已从组 {group_name} 移除 {', '.join(provider_ids)}")
            else:
                yield event.plain_result(f"路由组 {group_name} 不存在。")

        elif action == "delete":
            if group_name in self.groups:
                del self.groups[group_name]
                if self.active_group == group_name:
                    self.active_group = "default"
                await self.put_kv_data("groups", self.groups)
                await self.put_kv_data("active_group", self.active_group)
                yield event.plain_result(f"✅ 已删除组 {group_name}")
            else:
                yield event.plain_result(f"路由组 {group_name} 不存在。")

        else:
            yield event.plain_result(f"未知操作: {action}。支持: add, set, remove, delete, list, use")

    @api_group.command("batch_add")
    async def batch_add_providers(self, event: AstrMessageEvent, prefix: str, base_url: str, api_key: str, models_str: str):
        """批量添加兼容 OpenAI 格式的模型提供商。"""
        models = [m.strip() for m in models_str.split(",") if m.strip()]
        if not models:
            yield event.plain_result("错误：请至少提供一个模型名（使用逗号分隔）。")
            return

        from astrbot.core import astrbot_config

        added_count = 0
        added_ids = []

        for model in models:
            provider_id = f"{prefix}/{model}"

            if any(p.get("id") == provider_id for p in astrbot_config["provider"]):
                continue

            new_provider = {
                "id": provider_id,
                "type": "openai_chat_completion",
                "enable": True,
                "key": [api_key],
                "config": {
                    "base_url": base_url,
                    "api_key": api_key,
                    "model": model,
                    "proxy": ""
                }
            }

            astrbot_config["provider"].append(new_provider)
            added_count += 1
            added_ids.append(provider_id)

            try:
                await self.context.provider_manager.reload(new_provider)
            except Exception as e:
                logger.error(f"API Manager: Failed to hot reload provider {provider_id}: {e}")

        if added_count == 0:
            yield event.plain_result("没有添加任何新的模型（可能 ID 已存在）。")
            return

        try:
            self.context.config_manager.default_conf.save_config()
        except Exception as e:
            logger.error(f"API Manager: Failed to save config.yml: {e}")
            yield event.plain_result(f"✅ 成功热加载了 {added_count} 个模型，但保存到配置文件失败，重启后可能失效。")
            return

        yield event.plain_result(f"✅ 成功批量添加了 {added_count} 个模型：\n{', '.join(added_ids)}\n使用 /api list 可查看当前状态。")

    @api_group.command("keywords")
    async def manage_keywords(self, event: AstrMessageEvent, action: str, keyword: str = None, weight: float = None):
        """管理场景检测关键词: keywords list | add <word> <weight> | remove <word>"""
        if action == "list":
            kw = self._scene_detector._reasoning.keywords
            msg = "📝 当前推理场景关键词权重:\n"
            for k, w in sorted(kw.items(), key=lambda x: -x[1])[:20]:
                msg += f"• `{k}`: {w}\n"
            yield event.plain_result(msg)

        elif action == "add":
            if not keyword or weight is None:
                yield event.plain_result("用法: /api keywords add <word> <weight>")
                return
            self._scene_detector.add_keyword(keyword, weight)
            yield event.plain_result(f"✅ 已添加关键词 '{keyword}' 权重 {weight}")

        elif action == "remove":
            if not keyword:
                yield event.plain_result("用法: /api keywords remove <word>")
                return
            self._scene_detector.remove_keyword(keyword)
            yield event.plain_result(f"✅ 已移除关键词 '{keyword}'")

        else:
            yield event.plain_result("用法: /api keywords list | add <word> <weight> | remove <word>")

    # ── Runtime error monitoring ─────────────────────────────────────

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, request):
        """在 LLM 请求前给受管理的 Provider 装上错误监控外壳（仅一次）。"""
        try:
            provider = self.context.get_using_provider(umo=event.unified_msg_origin)
        except Exception:
            return
        if not provider:
            return

        p_id = provider.provider_config.get("id")
        if not p_id:
            return

        # Check circuit breaker
        cb = self._cb_registry.get(p_id)
        if cb.is_open:
            logger.warning(f"API Manager: Provider '{p_id}' circuit is OPEN, blocking request")
            # Try to find fallback
            if self.active_group in self.groups:
                for fallback_id in self.groups[self.active_group]:
                    if fallback_id != p_id:
                        fallback_cb = self._cb_registry.get(fallback_id)
                        if not fallback_cb.is_open:
                            # Switch to fallback
                            try:
                                from astrbot.core.provider.entities import ProviderType
                                await self.context.provider_manager.set_provider(
                                    provider_id=fallback_id,
                                    provider_type=ProviderType.CHAT_COMPLETION,
                                    umo=event.unified_msg_origin
                                )
                                yield event.plain_result(f"♻️ [熔断切换] {p_id} 已熔断，自动切换至 {fallback_id}")
                                return
                            except Exception as e:
                                logger.error(f"API Manager: Failed to switch to fallback {fallback_id}: {e}")

        all_managed_ids: set = set()
        for g in self.groups.values():
            all_managed_ids.update(g)
        if p_id not in all_managed_ids:
            return

        if getattr(provider, "_api_mgr_wrapped", False):
            return

        original_text_chat = provider.text_chat
        original_text_chat_stream = provider.text_chat_stream
        plugin_ref = self

        async def wrapped_text_chat(*args, _pid=p_id, **kwargs):
            try:
                result = await original_text_chat(*args, **kwargs)
                plugin_ref._cb_registry.get(_pid).record_success()
                return result
            except Exception as e:
                plugin_ref._cb_registry.get(_pid).record_failure(e)
                await plugin_ref._handle_runtime_error(_pid, e)
                raise

        async def wrapped_text_chat_stream(*args, _pid=p_id, **kwargs):
            try:
                async for resp in original_text_chat_stream(*args, **kwargs):
                    yield resp
                plugin_ref._cb_registry.get(_pid).record_success()
            except Exception as e:
                plugin_ref._cb_registry.get(_pid).record_failure(e)
                await plugin_ref._handle_runtime_error(_pid, e)
                raise

        provider.text_chat = wrapped_text_chat
        provider.text_chat_stream = wrapped_text_chat_stream
        provider._api_mgr_wrapped = True

    async def _handle_runtime_error(self, p_id: str, e: Exception):
        """捕获运行时异常并更新余额缓存以隔离问题 Provider。"""
        err_str = str(e)

        # Log failed route for statistics (error rates)
        group_name = self.active_group
        try:
            if group_name in self.groups and p_id in self.groups[group_name]:
                self._stats.log_route(
                    group_name=group_name,
                    provider_id=p_id,
                    scene="",
                    success=False,
                    error_type=type(e).__name__,
                )
        except Exception as stats_err:
            logger.debug(f"API Manager: Failed to log failed route to stats: {stats_err}")
        if any(pattern in err_str for pattern in QUOTA_ERROR_PATTERNS):
            logger.warning(f"API Manager: Quota/auth error detected for '{p_id}', marking as unavailable. Error: {err_str[:120]}")
            self.balance_cache[p_id] = {
                "remaining": 0,
                "error": f"Runtime Error: {err_str[:80]}",
                "last_check": time.time()
            }
            try:
                await self.put_kv_data("balance_cache", self.balance_cache)
            except Exception as kv_err:
                logger.error(f"API Manager: Failed to persist balance_cache after runtime error: {kv_err}")

    # ── Message routing ──────────────────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def on_message(self, event: AstrMessageEvent):
        """拦截消息并应用路由策略（自动场景切换 + 余额感知路由）。"""
        if event.message_str.startswith("/api"):
            return

        msg_text = event.message_str
        group_name = self.active_group
        scene_switch_reason = None
        scene_result: DetectionResult | None = None

        # Auto Scene Routing (if enabled and both daily + reasoning groups exist)
        if self.auto_scene_enabled and "daily" in self.groups and "reasoning" in self.groups:
            scene_result = self._scene_detector.detect(msg_text)
            if scene_result.category == "reasoning":
                group_name = "reasoning"
                if self.active_group != "reasoning":
                    scene_switch_reason = f"检测到复杂任务 (置信度: {scene_result.confidence:.0%})"
            else:
                group_name = "daily"

        if group_name not in self.groups or not self.groups[group_name]:
            return

        group_providers = self.groups[group_name]

        # Build route list with balance checks
        routes = [
            ProviderRoute(provider_id=p_id, enabled=self._is_balance_sufficient(p_id))
            for p_id in group_providers
        ]

        # Use balancer to select provider
        decision = await self._balancer.route(
            group_name=group_name,
            routes=routes,
            strategy=RoutingStrategy.PRIORITY,
        )

        selected_provider_id = decision.selected_provider_id

        logger.debug(
            f"API Manager: Routing {event.unified_msg_origin} → {selected_provider_id} "
            f"(group={group_name}, scene={scene_result.category if scene_result else 'N/A'})"
        )

        # Log route
        self._stats.log_route(
            group_name=group_name,
            provider_id=selected_provider_id,
            scene=scene_result.category if scene_result else "",
            success=True,
        )

        # Track usage
        self.usage_cache[selected_provider_id] = self.usage_cache.get(selected_provider_id, 0) + 1
        try:
            await self.put_kv_data("usage_cache", self.usage_cache)
        except Exception as e:
            logger.warning(f"API Manager: Failed to persist usage_cache: {e}")

        # Switch provider if needed
        try:
            current_provider = self.context.get_using_provider(umo=event.unified_msg_origin)
        except Exception:
            current_provider = None

        if current_provider and current_provider.meta().id != selected_provider_id:
            try:
                from astrbot.core.provider.entities import ProviderType
                await self.context.provider_manager.set_provider(
                    provider_id=selected_provider_id,
                    provider_type=ProviderType.CHAT_COMPLETION,
                    umo=event.unified_msg_origin
                )
                if scene_switch_reason:
                    yield event.plain_result(
                        f"🧠 [智能场景切换] {scene_switch_reason}，已自动分配模型组 ({group_name}): {selected_provider_id}"
                    )
                else:
                    yield event.plain_result(
                        f"♻️ [API 自动路由] 当前提供商额度不足，已自动切换至: {selected_provider_id}"
                    )
            except Exception as e:
                logger.error(f"API Manager: Failed to switch provider: {e}")

        # Set fallback chain
        if decision.fallback_chain:
            event.set_extra("fallback_chat_models", decision.fallback_chain)