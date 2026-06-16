# Codex 接国内 LLM

一键配置 Codex 接入国内大模型，支持 **DeepSeek / Qwen / Kimi / GLM**。

## 功能

- 🎯 交互式选模型 + 输 Key，一次搞定
- 🔄 自动配置 relay 转发代理
- 🚀 开机自启 + 每 6 小时自动保活
- 🪟 支持 Windows / 🍎 支持 macOS

## 使用

### Windows
1. 安装 [Codex](https://codex.openai.com) 
2. 右键 → **管理员身份运行** `WIN-codex辅助安装/Codex Complete Setup.bat`
3. 按提示选模型、输 API Key

### macOS
1. 安装 Codex
2. 双击 `MAC-codex辅助安装/codex-setup-macos.command`
3. 按提示操作

## 模型

| 厂商 | 模型 |
|------|------|
| DeepSeek | V4 Pro, V4 Flash |
| Qwen | Max, Plus, Turbo, Coder Plus, VL Max, 3.6 Plus, 3.5 Plus |
| Kimi | K2.6, K2.5 |
| GLM | 4.7 Flash, 4 Flash, 4 Plus, 4V Flash, 4 Long, 5.1, 5V Turbo, 5 |

## 目录

```
├── WIN-codex辅助安装/
│   ├── Codex Complete Setup.bat    # Windows 一键配置
│   ├── think_filter.py             # 思考过滤器
│   └── 说明.txt                     # 使用说明
├── MAC-codex辅助安装/
│   ├── codex-setup-macos.command   # macOS 配置脚本
│   ├── think_filter.py
│   ├── think_filter_debug.py
│   └── 说明.txt
└── .gitignore
```
