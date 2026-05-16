# 🚀 AstrBot API Manager ( API 管家)

<p align="center">
  <img src="https://img.shields.io/github/v/release/KardeniaPoyu/astrbot_plugin_api_manager?style=flat-square" alt="release">
  <img src="https://img.shields.io/github/license/KardeniaPoyu/astrbot_plugin_api_manager?style=flat-square" alt="license">
</p>

为 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 打造的批量 API 全自动管理和切换插件。
当你拥有数十个不同厂商的 API Key（有的免费、有的付费、有的擅长推理、有的额度极少），或者一个拥有上百个模型的 API Key 时，本插件能帮你**将它们全部整合、批量管理，并在额度耗尽时实现 0 延迟的全自动无缝切换**。

告别“发消息报错 -> 手动查余额 -> 手动切模型”的繁琐流程，让机器人进入自动驾驶模式。

---

## 🌟 核心优势 (Why Choose This?)

### 1. 📦 批量管理：你的模型 API 中枢
- **大一统可视化管理**：一键执行 `/api list`，即可像看板一样，清晰看到你所有 API Key 的剩余额度、探针健康状态、以及每个模型成功接客的“路由次数”。
- **兼容所有主流平台**：深度打通 DeepSeek, SiliconFlow, Moonshot (Kimi), OneAPI/NewAPI，更**特别支持了阿里云 (DashScope)** 的单模型细粒度状态探测。

### 2. ⚡ 死链秒切：全自动故障容灾 (Auto Failover)
- **额度耗尽？自动抛弃**：插件会在你聊天时精准拦截 403 (免费额度用完) 或余额不足报错。
- **无缝接力调度**：一旦发现当前 API 没钱了，插件会在 1 毫秒内自动顺延，将消息发送给你配置好的“备用模型”，并调用 AstrBot 底层接口**正式切换会话模型**，过程丝滑无感。

### 3. 🧠 意图感知识别：日常与推理自动分离
- **聊天用免费，算题用付费**：如果你同时配置了 `daily` 和 `reasoning` 组，插件会在收到消息时自动进行“意图判定”。
- **全自动场景切换**：遇到“代码、报错、推导”等复杂关键词或长文本，它会自动唤醒强大的推理模型（如 DeepSeek-R1）；遇到日常打招呼，自动切回廉价模型（如 Qwen-Turbo），帮你把好钢用在刀刃上。

---

## 🚀 快速开始

### 安装
在 AstrBot WebUI 的“插件”页面，点击“安装插件”，输入本仓库地址：
`https://github.com/KardeniaPoyu/astrbot_plugin_api_manager`

### 极简配置流：构建你的“模型防波堤”

1. **配置你的“日常防波堤” (daily)**
   *把白嫖的、不稳定的 API 放前面，稳定付费的放后面兜底*
   ```text
   /api group set daily aliyun_turbo sf_free qwen_paid
   ```

2. **配置你的“最强大脑” (reasoning)**
   *便宜的推理模型放前面，昂贵的放后面*
   ```text
   /api group set reasoning deepseek_r1 kimi_k2.6
   ```

3. **享受自动驾驶**
   现在开始聊天即可！遇到难题它会自动切到 reasoning，其中某个 API 没额度了它会自动切到下一个。

---

## 📖 指令大全

| 指令 | 说明 |
| :--- | :--- |
| `/api list` | **[核心]** 以原生风格列出所有模型的：ID、真实模型名、余额状态及路由次数 |
| `/api group set <name> <ids...>` | **[核心]** 批量设置组内成员，排序即代表**切换优先级**（排前面的优先用） |
| `/api balance [id]` | 手动批量触发余额/健康度查询探针 |
| `/api set_type <id> <type>` | 强制设置探针类型 (deepseek, siliconflow, aliyun, oneapi, etc.) |
| `/api group list` | 查看当前所有路由组配置 |
| `/api group use <name>` | 强制覆盖自动路由，手动切换当前激活的场景组 |
| `/api min_balance <val>` | 设置自动切换的死链判定余额阈值 (默认 0.01) |

---
