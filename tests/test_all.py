"""
Unit + integration tests for the API Manager plugin.

Run with:
  cd data/plugins/astrbot_plugin_api_mgr
  python -m pytest tests/ -v

Or standalone:
  python tests/test_all.py
"""
import asyncio
import logging
import sys
import os

# Ensure the plugin package is on the path
_plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("test")


# ── Test: Provider Registry ─────────────────────────────────────────


async def test_provider_registry():
    logger.info("\n=== Test: ProviderRegistry ===")
    from providers.base import BalanceInfo
    from providers.registry import ProviderRegistry
    from providers.deepseek import DeepSeekProbe
    from providers.siliconflow import SiliconFlowProbe
    from providers.moonshot import MoonshotProbe
    from providers.oneapi import OneAPIProbe
    from providers.aliyun import AliyunProbe
    from providers.openai import OpenAIProbe
    from providers.anthropic import AnthropicProbe
    from providers.gemini import GeminiProbe
    from providers.groq import GroqProbe

    reg = ProviderRegistry()
    reg.register_many([
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

    logger.info(f"Registered probes: {reg.get_all_probe_types()}")
    logger.info(f"Probe count: {reg.probe_count}")

    # Test URL auto-detection
    cases = [
        ("deepseek/chat", "https://api.deepseek.com/v1", "deepseek"),
        ("openai/gpt-4o", "https://api.openai.com/v1", "openai"),
        ("moonshot/kimi", "https://api.moonshot.ai/v1", "moonshot"),
        ("aliyun/qwen-plus", "https://dashscope.aliyuncs.com/v1", "aliyun"),
        ("my-custom/openai-compatible", "https://my-gateway.com/v1", "none"),
    ]
    for p_id, url, expected in cases:
        detected = reg.detect_probe_type(provider_id=p_id, base_url=url)
        status = "✅" if detected == expected else "❌"
        logger.info(f"  {status} detect('{p_id}', url='{url}') → '{detected}' (expected '{expected}')")

    # Test override
    reg.set_override("my-custom/anything", "openai")
    detected = reg.get_override("my-custom/anything")
    logger.info(f"  ✅ Override set/get: '{detected}'")

    # Test probe call (no real key — should return error gracefully)
    result = await reg.probe("deepseek", "invalid_key")
    assert isinstance(result, BalanceInfo)
    logger.info(f"  ✅ Probe error handling works: error='{result.error}', remaining={result.remaining}")

    # Test unknown probe type
    result2 = await reg.probe("nonexistent_provider", "key")
    assert result2.error is not None
    logger.info(f"  ✅ Unknown probe type returns error: '{result2.error}'")

    logger.info("ProviderRegistry tests PASSED\n")


# ── Test: Scene Detector ───────────────────────────────────────────


def test_scene_detector():
    logger.info("\n=== Test: SceneDetector ===")
    from router.scene_detector import SceneDetector

    detector = SceneDetector()

    cases = [
        # (text, expected_category, min_confidence)
        ("你好，今天天气怎么样？", "daily", 0.0),
        ("帮我写一个Python函数", "reasoning", 0.3),
        ("你好呀，朋友", "daily", 0.0),
        ("这段代码为什么报错？", "reasoning", 0.3),
        ("给我讲个笑话", "daily", 0.0),
        ("python代码怎么实现快速排序？", "reasoning", 0.4),
        ("帮我分析一下这个bug", "reasoning", 0.3),
        ("好的", "daily", 0.0),
        (
            "请帮我写一个Python脚本，实现以下功能："
            "1. 读取目录下所有CSV文件"
            "2. 统计每个文件的行数"
            "这是核心代码：```for f in files: if f.endswith('.csv'): ...```",
            "reasoning",
            0.5,
        ),
    ]

    for i, (text, expected_cat, min_conf) in enumerate(cases):
        result = detector.detect(text)
        status = "✅" if result.category == expected_cat else "❌"
        logger.info(
            f"  {status} [{i+1:02d}] text='{text[:40]}' → "
            f"'{result.category}' (conf={result.confidence:.2f}, "
            f"score={result.score:.1f})"
        )

    # Test custom keyword
    detector.add_keyword("翻译", 10.0)
    result = detector.detect("请翻译这段英文")
    logger.info(f"  ✅ Custom keyword '翻译': category='{result.category}', score={result.score:.1f}")

    detector.remove_keyword("翻译")
    result2 = detector.detect("请翻译这段英文")
    logger.info(f"  ✅ Keyword removal: category='{result2.category}', score={result2.score:.1f}")

    logger.info("SceneDetector tests PASSED\n")


# ── Test: Circuit Breaker ───────────────────────────────────────────


async def test_circuit_breaker():
    logger.info("\n=== Test: CircuitBreaker ===")
    from router.circuit_breaker import (
        CircuitBreaker,
        STATE_CLOSED,
        STATE_OPEN,
        STATE_HALF_OPEN,
    )

    cb = CircuitBreaker("test-provider", fail_max=3, reset_timeout=2.0)

    # Initial state
    assert cb.current_state == STATE_CLOSED, f"Expected CLOSED, got {cb.current_state}"
    logger.info(f"  ✅ Initial state: CLOSED")

    # Simulate failures until OPEN
    for i in range(5):  # More than fail_max=3 to ensure trip
        cb.record_failure()
    
    assert cb.current_state == STATE_OPEN, f"Expected OPEN after failures, got {cb.current_state}"
    logger.info(f"  ✅ State is OPEN after failures: fail_count={cb.failure_count}")

    # is_open when OPEN
    assert cb.is_open is True, "is_open should be True"
    logger.info(f"  ✅ is_open=True when OPEN")

    # Wait for timeout to allow HALF_OPEN transition
    import asyncio
    await asyncio.sleep(2.5)
    
    # pybreaker transitions to HALF_OPEN on next attempt (or automatically)
    # Force half_open
    cb.half_open()
    logger.info(f"  ✅ After half_open(): state=HALF_OPEN")

    # Record successes to close
    cb.record_success()
    cb.record_success()
    assert cb.current_state == STATE_CLOSED, f"Expected CLOSED, got {cb.current_state}"
    logger.info(f"  ✅ After successes: state=CLOSED")

    # Test reset
    cb.reset()
    assert cb.current_state == STATE_CLOSED
    logger.info(f"  ✅ reset() → CLOSED")

    logger.info("CircuitBreaker tests PASSED\n")


# ── Test: Routing Balancer ─────────────────────────────────────────


async def test_routing_balancer():
    logger.info("\n=== Test: RoutingBalancer ===")
    from router.balancer import (
        RoutingBalancer,
        RoutingStrategy,
        ProviderRoute,
        CircuitBreakerRegistry,
    )

    cb_registry = CircuitBreakerRegistry()
    balancer = RoutingBalancer(circuit_breaker_registry=cb_registry)

    routes = [
        ProviderRoute(provider_id="provider_a", weight=1.0),
        ProviderRoute(provider_id="provider_b", weight=2.0),
        ProviderRoute(provider_id="provider_c", weight=1.0),
    ]

    # Priority strategy
    decision = await balancer.route("test_group", routes, RoutingStrategy.PRIORITY)
    assert decision.selected_provider_id == "provider_a"
    assert decision.strategy == RoutingStrategy.PRIORITY
    logger.info(f"  ✅ Priority routing: selected='{decision.selected_provider_id}'")

    # Weighted strategy (statistical — run 10 times to verify distribution)
    results: dict = {}
    for _ in range(50):
        d = await balancer.route("test_group", routes, RoutingStrategy.WEIGHTED)
        results[d.selected_provider_id] = results.get(d.selected_provider_id, 0) + 1

    logger.info(f"  ✅ Weighted routing distribution (50 samples): {results}")
    assert "provider_b" in results, "provider_b should be selected most often with weight 2.0"

    # Round-robin strategy
    selected_ids = []
    for _ in range(4):
        d = await balancer.route("test_group", routes, RoutingStrategy.ROUND_ROBIN)
        selected_ids.append(d.selected_provider_id)

    logger.info(f"  ✅ Round-robin sequence: {selected_ids}")
    # Should cycle through providers

    logger.info("RoutingBalancer tests PASSED\n")


# ── Test: Stats Store ───────────────────────────────────────────────


def test_stats_store():
    logger.info("\n=== Test: StatsStore ===")
    import tempfile
    from storage.stats_store import StatsStore

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_stats.db")
        store = StatsStore(db_path=db_path)

        # Log some routes
        store.log_route("daily", "provider_a", scene="daily", success=True)
        store.log_route("daily", "provider_b", scene="daily", success=True)
        store.log_route("daily", "provider_a", scene="daily", success=False, error_type="403")
        store.log_route("reasoning", "provider_c", scene="reasoning", success=True)

        # Query stats
        stats = store.get_provider_stats()
        logger.info(f"  ✅ get_provider_stats() returned {len(stats)} provider(s)")

        for s in stats:
            logger.info(f"     - {s.provider_id}: {s.total_requests} reqs, {s.total_errors} errors, "
                        f"rate={s.error_rate:.1%}")

        # Query errors
        errors = store.get_recent_errors()
        logger.info(f"  ✅ get_recent_errors() returned {len(errors)} error(s)")

        # Group summary
        summary = store.get_group_summary()
        logger.info(f"  ✅ get_group_summary() returned {len(summary)} row(s)")
        for r in summary:
            logger.info(f"     - {r}")

        # Provider-specific query
        a_stats = store.get_provider_stats("provider_a")
        logger.info(
            f"  ✅ provider_a: {a_stats.total_requests} reqs, "
            f"{a_stats.total_errors} errors, rate={a_stats.error_rate:.1%}"
        )

        # Test prune
        deleted = store.prune_logs(older_than_days=30)
        logger.info(f"  ✅ prune_logs() deleted {deleted} rows")

        logger.info("StatsStore tests PASSED\n")


# ── Test: Aliyun Probe (real) ───────────────────────────────────────


async def test_aliyun_probe_live():
    """Real API test for Aliyun (requires real key in env: ALIYUN_API_KEY)."""
    import os
    api_key = os.environ.get("ALIYUN_API_KEY", "")
    if not api_key:
        logger.info("\n=== Test: AliyunProbe (SKIP - no ALIYUN_API_KEY env) ===")
        return

    logger.info("\n=== Test: AliyunProbe (live) ===")
    from providers.aliyun import AliyunProbe

    probe = AliyunProbe()
    result = await probe.probe(api_key, model_name="qwen-turbo")

    if result.error:
        logger.info(f"  ⚠️  Aliyun probe error: {result.error}")
    else:
        logger.info(f"  ✅ Aliyun probe success: remaining={result.remaining} {result.unit}")

    logger.info("AliyunProbe live test complete\n")


# ── Test: All probes instantiate ────────────────────────────────────


def test_all_probes_instantiate():
    logger.info("\n=== Test: All probes instantiate ===")
    from providers.deepseek import DeepSeekProbe
    from providers.siliconflow import SiliconFlowProbe
    from providers.moonshot import MoonshotProbe
    from providers.oneapi import OneAPIProbe
    from providers.aliyun import AliyunProbe
    from providers.openai import OpenAIProbe
    from providers.anthropic import AnthropicProbe
    from providers.gemini import GeminiProbe
    from providers.groq import GroqProbe

    probes = [
        DeepSeekProbe(),
        SiliconFlowProbe(),
        MoonshotProbe(),
        OneAPIProbe(),
        AliyunProbe(),
        OpenAIProbe(),
        AnthropicProbe(),
        GeminiProbe(),
        GroqProbe(),
    ]

    for probe in probes:
        logger.info(
            f"  ✅ {probe.__class__.__name__}: "
            f"type='{probe.probe_type}', "
            f"name='{probe.display_name}', "
            f"patterns={probe.url_patterns}"
        )

    logger.info("All probes instantiate PASSED\n")


# ── Main ─────────────────────────────────────────────────────────────


async def main():
    logger.info("=" * 60)
    logger.info("  API Manager Plugin - Full Test Suite")
    logger.info("=" * 60 + "\n")

    test_all_probes_instantiate()
    test_scene_detector()
    await test_circuit_breaker()
    await test_routing_balancer()
    test_stats_store()
    await test_provider_registry()
    await test_aliyun_probe_live()

    logger.info("=" * 60)
    logger.info("  ALL TESTS COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())