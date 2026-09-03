# Codex 接国内 LLM

一键配置 Codex 接入国内大模型，支持 **DeepSeek / Qwen / Kimi / GLM / MiniMax / 小米 MiMo / 腾讯混元**。

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
| DeepSeek | V4 Pro, V4 Flash, V4 Flash Vision (exp) |
| Qwen | 3.8 Max, 3.7 Max |
| Kimi | K3, K2.7 Code |
| GLM | glm-5.3, glm-5.3-flash（标准 API，flash 限时五折） |
| GLM Coding Plan | glm-5.3, glm-5.3-flash（多模态）（套餐额度，与标准 API 独立；两类模型都各有套餐/标准 API 两种计费，菜单按模型大小排序） |
| MiniMax | M3, M2.7（支持 Token Plan 订阅 Key） |
| 小米 MiMo | mimo-v2.5-pro, mimo-v2.5（支持 Token Plan 订阅 Key） |
| 腾讯混元 | hy3, hy4-preview（同一 Token Plan，共用 URL 与 Key） |

> Token Plan / Coding Plan：订阅 Key（`tp-` 开头）与按量 API Key（`sk-` 开头）
> 相互独立，脚本分别录入。汇聚模式下两者都录时会询问「默认用哪种计费」，
> 选择结果保存在 `auth.json` 的 `BILLING_PREF_*` 字段，网关按此路由。
> 小米 MiMo 的 Token Plan 走专属网关 `token-plan-cn.xiaomimimo.com`，
> 与按量 `api.xiaomimimo.com` 不通用。
> GLM Coding Plan 套餐（个人编程套餐 > 套餐概览 新建 Key）只走官方支持的
> 编码工具（Codex 在列），自建应用不能使用套餐额度。relay 转发走 OpenAI Chat
> 协议端点 `https://open.bigmodel.cn/api/coding/paas/v4`（官方文档标注），
> 与标准 API 的 `paas/v4` 相互独立。glm-5.3-flash 为原生多模态（支持图片输入）。
>
> 腾讯混元 hy3 / hy4-preview 同属一个 Token Plan，共用端点
> `https://api.lkeap.cloud.tencent.com/plan/v3` 与同一把 API Key，录入一次即可。

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
