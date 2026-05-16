# 🚀 AstrBot API Manager (API 管理器)

<p align="center">
  <img src="https://img.shields.io/github/v/release/KardeniaPoyu/astrbot_plugin_api_manager?style=flat-square" alt="release">
  <img src="https://img.shields.io/github/license/KardeniaPoyu/astrbot_plugin_api_manager?style=flat-square" alt="license">
  <img src="https://img.shields.io/github/stars/KardeniaPoyu/astrbot_plugin_api_manager?style=flat-square" alt="stars">
</p>

为 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 打造的专业级 API 智能调度插件。它不仅是一个余额查询工具，更是一个强大的**智能负载均衡器**和**意图感知调度中心**。

---

## 🌟 核心特性

### 1. 🛰️ 多渠道状态感知 (Health Check)
- **多平台支持**：深度适配 DeepSeek, SiliconFlow, Moonshot (Kimi), 阿里云(DashScope/百炼), OneAPI/NewAPI 等。
- **智能探测**：支持阿里云等无余额接口平台的**特定模型可用性探测**（模拟 1-token 生成），确保 Key 和模型均处于可用状态。

### 2. 🧠 智能意图识别 (Auto-Scene Switching)
- **场景自动驾驶**：通过关键词和内容长度识别，自动在 `daily` (日常闲聊) 和 `reasoning` (复杂推理/编程) 路由组之间**无缝切换**。
- **零配置体验**：只需命名对应的路由组，插件即可自动接管决策。

### 3. 🛡️ 自动故障迁移与负载均衡 (Failover)
- **优先级路由**：组内模型按需排序，优先使用免费/廉价资源，自动兜底昂贵模型。
- **正式状态同步**：当发生切换时，自动调用 AstrBot 原生 `set_provider` 接口，确保会话状态在系统层级持久化。

### 4. 📊 可视化仪表盘 (Dashboard)
- **仿原生 UI**：`/api list` 采用与 `/provider` 一致的排版风格，带有 `👈 (当前)` 指示器。
- **使用量统计**：实时追踪每个 API 的成功路由次数，一眼看出哪个 Key 贡献最大。

---

## 🚀 快速开始

### 安装
在 AstrBot WebUI 的“插件”页面，点击“安装插件”，输入本仓库地址：
`https://github.com/KardeniaPoyu/astrbot_plugin_api_manager`

### 基础配置指南 (推荐)

1. **设置查询类型**（插件会自动尝试识别，但手动设置更精准）：
   ```text
   /api set_type <provider_id> aliyun
   ```
2. **配置自动驾驶路由组**：
   ```text
   # 配置日常组（优先白嫖，不行就付钱）
   /api group set daily siliconflow_free qwen_plus
   
   # 配置推理组（专门用于写代码和解决难题）
   /api group set reasoning deepseek_r1 kimi_k2.6
   ```
3. **享受自动调度**：
   现在你可以直接开始聊天了。插件会自动检测你的提问难度并为你挑选最合适的模型。

---

## 📖 指令大全

| 指令 | 说明 |
| :--- | :--- |
| `/api list` | 以原生风格列出所有提供商 ID、模型、状态及路由次数 |
| `/api balance [id]` | 查询并刷新所有或特定提供商的余额/可用性缓存 |
| `/api set_type <id> <type>` | 设置探针类型 (deepseek, siliconflow, aliyun, oneapi, etc.) |
| `/api group list` | 查看当前所有路由组配置 |
| `/api group set <name> <ids...>` | **[推荐]** 显式设置组内成员及其优先级顺序 |
| `/api group use <name>` | 手动强制切换当前激活的路由组 |
| `/api min_balance <val>` | 设置自动切换的余额阈值 (默认 0.01) |

---

## 📄 开源协议
[MIT License](LICENSE)

---
**由 KardeniaPoyu 倾力打造，让 AI 接入更简单、更智能。**
