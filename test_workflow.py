import asyncio
import sys
import os

from api_service import ApiService

async def main():
    api_key = "sk-271406e9a2174c77959151998d36a9a8"
    print("--- 模拟 AstrBot 插件工作流测试 ---\n")
    
    # 模拟 AstrBot 中的提供商配置
    providers = [
        {"id": "aliyun_turbo", "model": "qwen-turbo"},
        {"id": "aliyun_plus", "model": "qwen-plus"}
    ]
    
    balance_cache = {}
    min_balance = 0.01

    print("1. 执行 /api balance，探测每个模型...")
    for p in providers:
        p_id = p["id"]
        model_name = p["model"]
        print(f" -> 正在探测 {p_id} (模型: {model_name})")
        balance = await ApiService.get_balance("aliyun", api_key, None, model_name)
        
        if "error" in balance:
            print(f"   [失败] 报错: {balance['error']}")
            if "remaining" in balance:
                balance_cache[p_id] = balance
        else:
            print(f"   [成功] 状态: {balance['unit']}")
            balance_cache[p_id] = balance

    print("\n当前缓存的额度状态 (balance_cache):")
    for k, v in balance_cache.items():
        print(f" - {k}: remaining = {v.get('remaining', 0)}")

    print("\n2. 模拟消息到达，开始路由选择...")
    # 假设这两个提供商在一个路由组里
    group_providers = ["aliyun_turbo", "aliyun_plus"]
    selected_provider_id = None
    
    for p_id in group_providers:
        print(f" -> 检查提供商: {p_id}")
        if p_id in balance_cache:
            rem = balance_cache[p_id].get("remaining", 0)
            if rem < min_balance:
                print(f"   [跳过] {p_id} 额度不足 (remaining: {rem})")
                continue
        print(f"   [命中] {p_id} 额度充足，选择此提供商！")
        selected_provider_id = p_id
        break

    if not selected_provider_id:
        selected_provider_id = group_providers[0]
        
    print(f"\n最终路由结果: 消息被发送给 [{selected_provider_id}]")

if __name__ == "__main__":
    asyncio.run(main())
