# AstrBot API Manager Plugin (api_mgr)

一个为 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 开发的模型路由及 API 管理插件。支持多渠道余额查询、路由分组管理、自动故障切换及负载均衡。

## 🌟 功能特性

- **多渠道余额查询**：支持 DeepSeek, SiliconFlow, Moonshot (Kimi), OneAPI/NewAPI 等主流提供商。
- **路由分组 (Router Groups)**：可将模型划分为不同组（如 `fast`, `smart`, `cheap`），根据需求灵活切换。
- **智能自动路由**：
    - **优先级排序**：根据配置顺序选择第一个可用的提供商。
    - **余额感应**：自动跳过余额不足（低于设定阈值）的提供商。
    - **自动 Fallback**：自动配置备用模型链，确保对话不中断。
- **简易配置**：全指令操作，无需手动修改配置文件。

## 🚀 安装

1. **通过管理面板安装（推荐）**：
   在 AstrBot WebUI 的“插件”页面，点击“安装插件”，输入本仓库地址即可。

2. **手动安装**：
   ```bash
   cd data/plugins
   git clone https://github.com/KardeniaPoyu/astrbot_plugin_api_mgr
   ```
   完成后重启 AstrBot 或在 WebUI 点击“重载插件”。

## 📖 指令说明

### 1. 提供商管理
- `/api list`：列出当前已配置的所有模型提供商 ID。
- `/api set_type <provider_id> <type>`：设置提供商的余额查询类型。
    - 支持类型：`deepseek`, `siliconflow`, `moonshot`, `oneapi`, `none`。
- `/api balance [provider_id]`：查询指定或所有提供商的账户余额并刷新缓存。

### 2. 路由与分组
- `/api group list`：列出所有路由组及其成员。
- `/api group add <group_name> <provider_ids...>`：添加提供商到指定路由组。
- `/api group remove <group_name> <provider_ids...>`：从路由组移除提供商。
- `/api group use <group_name>`：切换当前激活的路由组。
- `/api min_balance <value>`：设置自动切换的最小余额阈值（默认 0.01）。

## 🛠️ 配置示例

1. **设置查询类型**：
   `/api set_type my_deepseek deepseek`
   `/api set_type my_sf siliconflow`

2. **创建路由组**：
   `/api group add fast my_sf my_deepseek`

3. **激活并使用**：
   `/api group use fast`

## 📄 开源协议

[MIT License](LICENSE)
