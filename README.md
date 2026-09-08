# codex-switch

[English README](README.EN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)]()
[![Shell](https://img.shields.io/badge/shell-bash-4EAA25.svg)]()
[![Codex](https://img.shields.io/badge/tested-Codex%200.153.4-blue.svg)]()


macOS 下 Codex（ChatGPT 桌面应用内置 CLI）的**多供应商一键切换**工具：在 OpenAI 官方（ChatGPT 会员）、DeepSeek、Kimi Code 之间秒切，**历史会话跨供应商无缝续聊**。

适用场景：GPT 会员额度用完/到期时用第三方模型顶班，额度恢复后切回官方——**双向老对话都能接着聊**，不用新开窗口重述上下文。

> 所有结论均为 2026-09 在 Codex 0.153.4 + CC Switch 3.20.1 上实测得出，非推测。

## 功能

- 一键切换：退出 Codex 应用 → 写入对应配置 → 同步会话显示标记 → 重启应用
- **跨供应商续聊自动化**（本项目核心价值，两个实测出来的坑都已内置处理）：
  1. **模型名改写**：codex 续聊时的 pre-sampling compact 钉死使用会话元数据里记录的模型名，与当前配置无关。跨供应商续聊会被对方 API 以 `invalid_request_error` 拒绝。脚本在每次切换时把历史会话 rollout 里的 `"model":"..."` 批量改写为目标供应商的模型名。
  2. **reasoning 残留清理**（仅切回官方时）：DeepSeek 直连 `/responses` 产生的 reasoning 项带 `content` 数组和本地 Fernet 加密的 `encrypted_content`，官方 API 会报 `array_above_max_length` / `invalid_encrypted_content`。切到 openai 时脚本递归剥离这两个字段，官方只收到 summary，可正常续聊。
- 所有改写/清理前自动留首次备份（`.bak-model` / `.bak-reasoning` / `.bak-switch`）
- 如已安装 CC Switch，自动同步其「使用中」标记（仅作面板展示）

## 为什么不能只用 CC Switch

CC Switch 点「启用」**只改它自己数据库的标记，不会写入 Codex 实际配置**——在 v3.19.2（issue #6236）和 v3.20.1（接管模式和普通模式均实测）上都验证过，日志显示"已接管"但 `~/.codex/config.toml` 的 mtime 根本未变。CC Switch 适合当配置仓库和用量面板，真实切换必须用本脚本。

## 安装

```bash
git clone https://github.com/aipmer/codex-switch.git
cd codex-switch
chmod +x codex-switch.sh *.command codeproxy-kimi.sh
```

1. 编辑 `config-deepseek.toml`，把 `YOUR_DEEPSEEK_API_KEY` 替换为你的 key
2. 需要 Kimi 的话，先装本地路由（见下节）
3. 使用：`./codex-switch.sh openai|deepseek|kimi`，或双击对应 `.command`

## Kimi 本地路由（codeproxy）

新版 Codex 只支持 Responses API 且强制携带 `tool_search` 工具，Kimi 的 `/responses` 端点不认识它，直连必报 `invalid_request_error: tool type "tool_search" is not supported`。官方解法即本地路由（<https://www.kimi.com/zh-hans/resources/codex-api>）：

1. 按 Kimi Code 官方文档安装 codeproxy：<https://www.kimi.com/code/docs/>
2. 编辑 `codeproxy-kimi.sh`，替换 `YOUR_KIMI_API_KEY`，复制到 `~/.codex/`（launchd 可能无权访问 Documents 等目录）
3. 编辑 `com.codexswitch.codeproxy-kimi.plist`，把两处 `REPLACE_WITH_HOME` 替换为你的 home 目录绝对路径，复制到 `~/Library/LaunchAgents/`
4. 加载：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.codexswitch.codeproxy-kimi.plist`
5. Codex 桌面版内置 MCP 工具的 schema 会被 Kimi 校验器拒绝（`moonshot flavored json schema` 报错），因此还需 schema 垫片：把 `schema-shim-kimi.py` 复制到 `~/.codex/`，编辑 `com.codexswitch.schema-shim-kimi.plist` 的两处 `REPLACE_WITH_*` 后同样放入 LaunchAgents 并 bootstrap。链路为 Codex → 垫片(8788) → codeproxy(8787) → Kimi；`config-kimi.toml` 的 `base_url` 指向 8788

之后 `codex-switch.sh kimi` 会自动确保路由在运行。

## 模型目录分家（可选但推荐）

若两套第三方配置共用一份模型目录（`model_catalog_json`），Codex 界面的模型选择器会把两家的模型全列出来——在 DeepSeek 模式选到 Kimi 模型会请求被拒。建议拆成两份各指各的：DeepSeek 模式只显示 `deepseek-v4-flash / deepseek-v4-pro`，Kimi 模式只显示 `kimi-for-coding / k3` 等。

目录文件可用 `codex debug models` 的输出生成，再按供应商拆分后分别在 `config-deepseek.toml` / `config-kimi.toml` 里用 `model_catalog_json` 指向。

## 注意事项

- **切换会整体覆盖 `~/.codex/config.toml`**：请把 projects 信任列表、插件、notify 等个性化配置合并进本仓库的三个模板，否则切换后丢失
- 改写以切换时刻为准，切换后新产生的会话天然是当前模型名，无需处理
- 官方↔第三方来回切换时模型名会被来回改写（如 gpt-5.6-luna → deepseek-v4-flash → gpt-5.6-sol），归属精度有损失但不影响功能，原始值在 `.bak-model` 里
- 剥离 reasoning 后这些会话的 reasoning 正文不可恢复（`.bak-reasoning` 有原始文件）；再切回第三方时这些 reasoning 项只剩空 summary，DeepSeek/Kimi 侧对此容错，实测不受影响
- 会话已归档时需先 `codex unarchive <会话ID>` 再续聊

## 故障排查

| 症状 | 检查 |
| --- | --- |
| kimi 模式报 Connection refused | `launchctl print gui/$(id -u)/com.codexswitch.codeproxy-kimi` 看状态；`tail ~/.codex/codeproxy-kimi.log` 看日志；`launchctl kickstart -k gui/$(id -u)/com.codexswitch.codeproxy-kimi` 重启 |
| kimi 模式报 401 | Key 过期/失效，去 Kimi Code 控制台重建，更新 `~/.codex/codeproxy-kimi.sh` 里的 `--apikey` 后 kickstart 重启 |
| kimi 模式报 `not a valid moonshot flavored json schema` | 配置绕过了垫片（8788）直连了 codeproxy（8787），检查 `base_url` |
| kimi 模式报 tool_search 不支持 | 配置走了直连而非路由，确认 `~/.codex/config.toml` 的 `base_url = "http://127.0.0.1:8787/v1"` |
| 切换后历史会话不见了 | 会话标记没同步，重跑一次切换脚本即可（脚本会翻转 `state_5.sqlite` 的 provider 标记） |
| 官方模式续聊旧对话报 `array_above_max_length` / `invalid_encrypted_content` | 第三方 reasoning 残留，切到 openai 时脚本会自动清理；仍遇到说明该会话是切换后新建的，重跑一次切换脚本 |
| 第三方模式续聊官方会话报 `passed gpt-5.x` | 会话元数据模型名未改写，重跑一次切换脚本 |
| 界面选到了别家模型 | 目录未分家，见「模型目录分家」一节 |
| 验证路由是否正常 | `curl -s http://127.0.0.1:8787/v1/responses -H "Content-Type: application/json" -d '{"model":"kimi-for-coding","input":"hi","stream":false}'` |

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CODEX_HOME` | `~/.codex` | Codex 配置目录 |
| `CODEX_SWITCH_APP` | `ChatGPT` | Codex 桌面应用名 |
| `CODEX_SWITCH_CLI` | `/Applications/ChatGPT.app/Contents/Resources/codex` | CLI 路径（用于打印版本） |
| `CODEX_SWITCH_LAUNCHD_LABEL` | `com.codexswitch.codeproxy-kimi` | Kimi 路由的 launchd Label |

## 文件清单

- `codex-switch.sh` — 切换主脚本
- `config-openai.toml` / `config-deepseek.toml` / `config-kimi.toml` — 三套配置模板
- `切换到*.command` — 双击入口
- `codeproxy-kimi.sh` + `com.codexswitch.codeproxy-kimi.plist` — Kimi 本地路由模板
- `schema-shim-kimi.py` + `com.codexswitch.schema-shim-kimi.plist` — Kimi schema 修正垫片模板

## License

MIT
