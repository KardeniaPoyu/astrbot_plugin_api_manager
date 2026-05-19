"""
Unit + integration tests for the API Manager plugin.

Run with:
  cd data/plugins/astrbot_plugin_api_mgr
  python -m pytest tests/ -v

Or standalone:
  python tests/test_all.py

Note: Async tests use asyncio.run() internally — no pytest-asyncio needed.
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


# ══════════════════════════════════════════════════════════════════════
# Helper: Fake probe (no network) — addresses Issue #4 (Sourcery)
# ══════════════════════════════════════════════════════════════════════

class FakeProbe:
    """A probe that returns synthetic responses without making network calls."""

    def __init__(self, probe_type: str, display_name: str, url_patterns: list[str]):
        self.probe_type = probe_type
        self.display_name = display_name
        self.url_patterns = url_patterns
        self._call_count = 0

    async def probe(self, api_key: str, base_url: str = "", model_name: str = ""):
        """Return a synthetic BalanceInfo based on the api_key value."""
        from providers.base import BalanceInfo

        self._call_count += 1
        if api_key == "invalid_key":
            return BalanceInfo(error="Fake: invalid key", remaining=0.0)
        if api_key == "error_key":
            return BalanceInfo(error="Fake: network error", remaining=0.0)
        return BalanceInfo(
            total=100.0,
            used=float(self._call_count) * 5.0,
            remaining=100.0 - float(self._call_count) * 5.0,
            unit="USD",
            error=None,
        )


# ══════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════

def test_all_probes_instantiate():
    """All 9 probe classes instantiate correctly — sync, no network."""
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

    expected_types = {
        "DeepSeekProbe": "deepseek",
        "SiliconFlowProbe": "siliconflow",
        "MoonshotProbe": "moonshot",
        "OneAPIProbe": "oneapi",
        "AliyunProbe": "aliyun",
        "OpenAIProbe": "openai",
        "AnthropicProbe": "anthropic",
        "GeminiProbe": "gemini",
        "GroqProbe": "groq",
    }

    for probe in probes:
        cls_name = probe.__class__.__name__
        expected_type = expected_types.get(cls_name, "unknown")
        logger.info(
            f"  ✅ {cls_name}: type='{probe.probe_type}', "
            f"name='{probe.display_name}', patterns={probe.url_patterns}"
        )
        # Issue #5: add assertions
        assert probe.probe_type == expected_type, f"{cls_name}: probe_type mismatch"
        assert probe.display_name, f"{cls_name}: display_name is empty"
        assert len(probe.url_patterns) > 0, f"{cls_name}: no url_patterns"

    logger.info("All probes instantiate PASSED\n")


# ── Test: Provider Registry (with fake probes, no network) ──────────


def test_provider_registry():
    """Registers fake probes and tests detection / override / error handling."""
    async def _run():
        logger.info("\n=== Test: ProviderRegistry ===")
        from providers.base import BalanceInfo
        from providers.registry import ProviderRegistry, global_registry

        reg = ProviderRegistry()

        # Register fake probes instead of real ones (Issue #4 fix)
        reg.register_many([
            FakeProbe("deepseek", "DeepSeek", ["api.deepseek.com"]),
            FakeProbe("openai", "OpenAI", ["api.openai.com"]),
            FakeProbe("moonshot", "Moonshot", ["api.moonshot.ai"]),
            FakeProbe("aliyun", "Aliyun DashScope", ["dashscope.aliyuncs.com"]),
        ])

        logger.info(f"Registered probes: {reg.get_all_probe_types()}")
        assert reg.probe_count == 4, f"Expected 4 probes, got {reg.probe_count}"
        logger.info(f"  ✅ Probe count: {reg.probe_count}")

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
            assert detected == expected, f"detect('{p_id}', url='{url}') → '{detected}' (expected '{expected}')"
            logger.info(f"  ✅ detect('{p_id}', url='{url}') → '{detected}'")

        # Test override
        reg.set_override("my-custom/anything", "openai")
        detected = reg.get_override("my-custom/anything")
        assert detected == "openai", f"Override failed: got '{detected}'"
        logger.info(f"  ✅ Override set/get: '{detected}'")

        # Test probe call with fake probe (error path)
        result = await reg.probe("deepseek", "invalid_key")
        assert isinstance(result, BalanceInfo), f"Expected BalanceInfo, got {type(result)}"
        assert result.error is not None, "Expected error for invalid_key"
        logger.info(f"  ✅ Probe error handling: error='{result.error}', remaining={result.remaining}")

        # Test probe call with fake probe (success path)
        result3 = await reg.probe("openai", "valid_key")
        assert result3.error is None, f"Expected no error, got '{result3.error}'"
        assert result3.remaining > 0, f"Expected positive remaining, got {result3.remaining}"
        logger.info(f"  ✅ Probe success: remaining={result3.remaining} {result3.unit}")

        # Test unknown probe type
        result2 = await reg.probe("nonexistent_provider", "key")
        assert result2.error is not None, "Expected error for unknown provider"
        logger.info(f"  ✅ Unknown probe type returns error: '{result2.error}'")

        # Test global registry
        from providers.deepseek import DeepSeekProbe
        global_registry.register(DeepSeekProbe())
        assert "deepseek" in global_registry.get_all_probe_types()
        logger.info("  ✅ Global registry works")

        logger.info("ProviderRegistry tests PASSED\n")

    asyncio.run(_run())


# ── Test: Scene Detector ────────────────────────────────────────────


def test_scene_detector():
    """Tests keyword matching, length scoring, and custom keywords with assertions."""
    logger.info("\n=== Test: SceneDetector ===")
    from router.scene_detector import SceneDetector

    detector = SceneDetector()

    cases = [
        # (text, expected_category, min_confidence)
        ("你好，今天天气怎么样？", "daily", 0.0),
        ("帮我写一个Python函数", "reasoning", 0.5),
        ("你好呀，朋友", "daily", 0.0),
        ("这段代码为什么报错？", "reasoning", 0.0),
        ("给我讲个笑话", "daily", 0.0),
        ("python代码怎么实现快速排序？", "reasoning", 0.2),
        ("帮我分析一下这个bug", "reasoning", 0.0),
        ("好的", "daily", 0.0),
        (
            "请帮我写一个Python脚本，实现以下功能：1. 读取目录下所有CSV文件 2. 统计每个文件的行数",
            "reasoning",
            0.3,
        ),
    ]

    failures = []
    for i, (text, expected_cat, min_conf) in enumerate(cases):
        result = detector.detect(text)
        cat_ok = result.category == expected_cat
        conf_ok = result.confidence >= min_conf
        status = "✅" if (cat_ok and conf_ok) else "❌"
        logger.info(
            f"  {status} [{i+1:02d}] text='{text[:40]}' → "
            f"'{result.category}' (conf={result.confidence:.2f}, score={result.score:.1f})"
        )
        # Issue #5: add assertions
        assert cat_ok, (
            f"Case [{i+1:02d}]: expected category '{expected_cat}', "
            f"got '{result.category}' for text='{text[:30]}'"
        )
        assert conf_ok, (
            f"Case [{i+1:02d}]: confidence={result.confidence:.2f} < min={min_conf}"
        )

    # Test custom keyword (add + verify)
    detector.add_keyword("翻译", 10.0)
    result = detector.detect("请翻译这段英文")
    assert result.category == "reasoning", (
        f"Custom keyword '翻译' failed: expected 'reasoning', got '{result.category}'"
    )
    assert result.score >= 10.0, f"Custom keyword score too low: {result.score}"
    logger.info(f"  ✅ Custom keyword '翻译': category='{result.category}', score={result.score:.1f}")

    # Test keyword removal
    detector.remove_keyword("翻译")
    result2 = detector.detect("请翻译这段英文")
    assert result2.category == "daily", (
        f"Keyword removal failed: expected 'daily' after removal, got '{result2.category}'"
    )
    logger.info(f"  ✅ Keyword removal: category='{result2.category}', score={result2.score:.1f}")

    # Edge case: empty input
    result3 = detector.detect("")
    assert result3.category in ("daily", "reasoning"), "Empty input should not crash"
    logger.info(f"  ✅ Empty input: category='{result3.category}'")

    logger.info("SceneDetector tests PASSED\n")


# ── Test: Circuit Breaker ───────────────────────────────────────────


def test_circuit_breaker():
    """Tests circuit breaker state transitions: CLOSED → OPEN → HALF_OPEN → CLOSED."""
    async def _run():
        logger.info("\n=== Test: CircuitBreaker ===")
        from router.circuit_breaker import (
            CircuitBreaker,
            STATE_CLOSED,
            STATE_OPEN,
            STATE_HALF_OPEN,
        )

        cb = CircuitBreaker("test-provider", fail_max=3, reset_timeout=2.0)

        # 1. Initial state must be CLOSED
        assert cb.current_state == STATE_CLOSED, f"Expected CLOSED, got {cb.current_state}"
        assert not cb.is_open, "is_open should be False initially"
        logger.info(f"  ✅ Initial state: CLOSED (is_open={cb.is_open})")

        # 2. Fail enough times to trigger OPEN
        for i in range(5):
            cb.record_failure()
        assert cb.current_state == STATE_OPEN, f"Expected OPEN, got {cb.current_state}"
        assert cb.is_open is True, "is_open should be True when OPEN"
        assert cb.failure_count > 0, "failure_count should be > 0"
        logger.info(f"  ✅ After {cb.failure_count} failures: state=OPEN")

        # 3. Force HALF_OPEN after timeout
        import asyncio
        await asyncio.sleep(2.5)
        cb.half_open()
        assert cb.current_state == STATE_HALF_OPEN, f"Expected HALF_OPEN, got {cb.current_state}"
        assert not cb.is_open, "is_open should be False when HALF_OPEN"
        logger.info(f"  ✅ After half_open(): state=HALF_OPEN (is_open={cb.is_open})")

        # 4. Successes close the circuit
        cb.record_success()
        cb.record_success()
        assert cb.current_state == STATE_CLOSED, f"Expected CLOSED, got {cb.current_state}"
        logger.info(f"  ✅ After successes: state=CLOSED")

        # 5. Reset always goes to CLOSED
        cb.reset()
        assert cb.current_state == STATE_CLOSED
        logger.info(f"  ✅ reset() → CLOSED")

        # 6. Registry test
        from router.circuit_breaker import CircuitBreakerRegistry
        reg = CircuitBreakerRegistry()
        cb_a = reg.get("provider_a")
        cb_b = reg.get("provider_b")
        assert cb_a is not None
        assert cb_b is not None
        assert reg.get("provider_a") is cb_a, "Registry should return same breaker instance"
        logger.info("  ✅ CircuitBreakerRegistry: lazy creation works")

        stats = reg.get_all()
        assert len(stats) == 2, f"Expected 2 stats, got {len(stats)}"
        # Issue #5: verify stats structure
        for p_id, s in stats.items():
            assert hasattr(s, "state"), f"Stats for {p_id} missing 'state'"
            assert hasattr(s, "total_failures"), f"Stats for {p_id} missing 'total_failures'"
            assert isinstance(s.state, str), f"Stats.state should be str, got {type(s.state)}"
            logger.info(f"     {p_id}: state={s.state}, failures={s.total_failures}")

        logger.info("CircuitBreaker tests PASSED\n")

    asyncio.run(_run())


# ── Test: Routing Balancer ─────────────────────────────────────────


def test_routing_balancer():
    """Tests PRIORITY, WEIGHTED, and ROUND_ROBIN routing with assertions."""
    async def _run():
        logger.info("\n=== Test: RoutingBalancer ===")
        from router.balancer import (
            RoutingBalancer,
            RoutingStrategy,
            ProviderRoute,
        )
        from router.circuit_breaker import CircuitBreakerRegistry

        cb_registry = CircuitBreakerRegistry()
        balancer = RoutingBalancer(circuit_breaker_registry=cb_registry)

        routes = [
            ProviderRoute(provider_id="provider_a", weight=1.0),
            ProviderRoute(provider_id="provider_b", weight=2.0),
            ProviderRoute(provider_id="provider_c", weight=1.0),
        ]

        # Priority strategy: first in list wins
        decision = await balancer.route("test_group", routes, RoutingStrategy.PRIORITY)
        assert decision.selected_provider_id == "provider_a", (
            f"Priority routing failed: expected 'provider_a', got '{decision.selected_provider_id}'"
        )
        assert decision.strategy == RoutingStrategy.PRIORITY
        assert len(decision.fallback_chain) > 0, "Fallback chain should not be empty"
        logger.info(
            f"  ✅ Priority routing: selected='{decision.selected_provider_id}' "
            f"(fallbacks: {decision.fallback_chain})"
        )

        # Weighted strategy: provider_b (weight=2.0) should dominate
        results: dict = {}
        for _ in range(50):
            d = await balancer.route("test_group", routes, RoutingStrategy.WEIGHTED)
            results[d.selected_provider_id] = results.get(d.selected_provider_id, 0) + 1

        logger.info(f"  ✅ Weighted routing (50 samples): {results}")
        assert "provider_b" in results, "provider_b should appear in weighted results"
        # provider_b has 2x weight, so it should be selected most often
        b_count = results.get("provider_b", 0)
        a_count = results.get("provider_a", 0)
        assert b_count >= a_count, (
            f"provider_b (weight=2.0) should dominate: b={b_count}, a={a_count}"
        )

        # Round-robin strategy: cycles through providers
        selected_ids = []
        for _ in range(4):
            d = await balancer.route("test_group", routes, RoutingStrategy.ROUND_ROBIN)
            selected_ids.append(d.selected_provider_id)

        logger.info(f"  ✅ Round-robin sequence (4 calls): {selected_ids}")
        assert len(set(selected_ids)) >= 2, "Round-robin should use multiple providers"
        assert selected_ids[0] == selected_ids[3], (
            f"Round-robin should cycle back: {selected_ids}"
        )

        # Edge case: empty routes
        from router.balancer import RoutingDecision
        empty_dec = await balancer.route("empty_group", [], RoutingStrategy.PRIORITY)
        assert isinstance(empty_dec, RoutingDecision), "Should return RoutingDecision even for empty routes"
        assert empty_dec.selected_provider_id in (None, ""), (
            f"Empty routes → no provider selected, got: '{empty_dec.selected_provider_id}'"
        )
        logger.info(f"  ✅ Empty routes: selected={empty_dec.selected_provider_id}")

        logger.info("RoutingBalancer tests PASSED\n")

    asyncio.run(_run())


# ── Test: Stats Store ───────────────────────────────────────────────


def test_stats_store():
    """Tests SQLite stats logging, querying, and pruning with assertions."""
    logger.info("\n=== Test: StatsStore ===")
    import tempfile
    from storage.stats_store import StatsStore

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_stats.db")
        store = StatsStore(db_path=db_path)

        # 1. Log routes (mix of success and failure for meaningful error rates)
        store.log_route("daily", "provider_a", scene="daily", success=True)
        store.log_route("daily", "provider_b", scene="daily", success=True)
        store.log_route("daily", "provider_a", scene="daily", success=False, error_type="403")
        store.log_route("daily", "provider_a", scene="daily", success=True)
        store.log_route("daily", "provider_a", scene="daily", success=False, error_type="Timeout")
        store.log_route("reasoning", "provider_c", scene="reasoning", success=True)

        # 2. Query all stats
        stats = store.get_provider_stats()
        assert len(stats) >= 2, f"Expected >= 2 providers, got {len(stats)}"
        logger.info(f"  ✅ get_provider_stats() returned {len(stats)} provider(s)")

        for s in stats:
            assert s.provider_id, "provider_id should not be empty"
            assert s.total_requests >= 0, "total_requests should be non-negative"
            assert 0.0 <= s.error_rate <= 1.0, f"error_rate out of range: {s.error_rate}"
            logger.info(
                f"     - {s.provider_id}: {s.total_requests} reqs, "
                f"{s.total_errors} errors, rate={s.error_rate:.1%}"
            )

        # 3. Verify error rate for provider_a (2 failures / 4 total = 50%)
        a_stats = store.get_provider_stats("provider_a")
        assert a_stats.total_requests == 4, f"provider_a should have 4 requests, got {a_stats.total_requests}"
        assert a_stats.total_errors == 2, f"provider_a should have 2 errors, got {a_stats.total_errors}"
        assert abs(a_stats.error_rate - 0.5) < 0.02, (
            f"provider_a error_rate should be ~0.5, got {a_stats.error_rate:.2%}"
        )
        logger.info(
            f"  ✅ provider_a stats: {a_stats.total_requests} reqs, "
            f"{a_stats.total_errors} errors, rate={a_stats.error_rate:.1%}"
        )

        # 4. Recent errors
        errors = store.get_recent_errors()
        assert len(errors) >= 1, f"Expected >= 1 error, got {len(errors)}"
        error_types = [e.error_type for e in errors]
        logger.info(f"  ✅ Recent errors ({len(errors)}): {error_types}")

        # 5. Group summary
        summary = store.get_group_summary()
        assert len(summary) == 3, f"Expected 3 (group×provider) rows, got {len(summary)}"
        logger.info(f"  ✅ get_group_summary(): {len(summary)} group×provider rows")
        for r in summary:
            logger.info(f"     - group='{r['group']}' provider='{r['provider']}': {r['count']} reqs")

        # 6. Prune old logs
        deleted = store.prune_logs(older_than_days=30)
        assert deleted >= 0, f"prune should return >= 0, got {deleted}"
        logger.info(f"  ✅ prune_logs(30d): deleted {deleted} rows")

        logger.info("StatsStore tests PASSED\n")


# ── Test: Aliyun Probe (live, optional) ─────────────────────────────


def test_aliyun_probe_live():
    """Real API test for Aliyun — only runs if ALIYUN_API_KEY is set in env."""
    async def _run():
        api_key = os.environ.get("ALIYUN_API_KEY", "")
        if not api_key:
            logger.info("\n=== Test: AliyunProbe (SKIP - no ALIYUN_API_KEY env) ===\n")
            return

        logger.info("\n=== Test: AliyunProbe (live) ===")
        from providers.aliyun import AliyunProbe

        probe = AliyunProbe()
        result = await probe.probe(api_key, model_name="qwen-turbo")

        assert probe.probe_type == "aliyun", f"Expected 'aliyun', got '{probe.probe_type}'"

        if result.error:
            logger.info(f"  ⚠️  Aliyun probe error: {result.error}")
        else:
            logger.info(f"  ✅ Aliyun probe success: remaining={result.remaining} {result.unit}")

        logger.info("AliyunProbe live test complete\n")

    asyncio.run(_run())


# ── Main ─────────────────────────────────────────────────────────────


def main():
    """Run all tests. Invoke with: python tests/test_all.py"""
    logger.info("=" * 60)
    logger.info("  API Manager Plugin - Full Test Suite")
    logger.info("=" * 60 + "\n")

    test_all_probes_instantiate()
    test_scene_detector()
    test_circuit_breaker()
    test_routing_balancer()
    test_stats_store()
    test_provider_registry()
    test_aliyun_probe_live()

    logger.info("=" * 60)
    logger.info("  ALL TESTS COMPLETE - PASSED ✅")
    logger.info("=" * 60)


# Allow running with pytest (sync tests) or standalone (main)
if __name__ == "__main__":
    main()