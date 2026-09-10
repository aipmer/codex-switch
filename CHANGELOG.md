# 更新日志

本项目的所有重要变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

[English](CHANGELOG.EN.md)

## [Unreleased]

### 修复

- **GUI 投影缓存失效（2026-09-09）**：Codex GUI 从 `thread_history_1.sqlite` 的投影（按字节偏移索引 rollout 文件）读取对话；脚本原地改写文件后偏移失效，GUI 会停在旧位置显示过期内容。现在脚本在改写/清理后自动失效受影响线程的投影，app 重启后从 jsonl 重建。（`4cae38c`）
- **官方模式续聊的四重校验（2026-09-08/09）**：第三方直连产生的历史项会依次触发官方 API 的四层校验——reasoning `content` 数组（`array_above_max_length`）、本地 Fernet `encrypted_content`（`invalid_encrypted_content`）、工具调用 `tool_` 前缀 id（`invalid_id_prefix`）、reasoning 的第三方 `rs_` id（`Item with id 'rs_...' not found`）。切到 openai 时脚本自动剥离 reasoning 的 content/encrypted_content/id 并把工具 id 前缀改为 `fc`，实测可正常续聊。（`15538dc`）
- **Kimi schema 校验（2026-09-08）**：新增 8788 端口 schema 垫片，修复 MCP 工具的 `$ref` + 兄弟 `type` 写法被 Kimi 校验器拒绝（`moonshot flavored json schema`）的问题，K3/K2.7 均实测 200。（`e6505f7`）

### 文档

- **双向续聊实测结论（2026-09-08）**：README 完整记录正/反向跨供应商续聊的实测结果、四层校验逐层症状与清理代价
- **故障排查表扩充（2026-09-09）**：新增「对话内容停在旧时间」「切换后对话从列表消失」两条症状，附 config 与 `state_5.sqlite` 标记一致性自查命令
- **CC Switch 定位定调（2026-09-07）**：实测确认 CC Switch（v3.19.2 / v3.20.1，含接管模式）点「启用」不会写入 `~/.codex/config.toml`，文档明确其仅作只读面板、真实切换必须走脚本
- 新增英文 README（`3285b92`）、徽章（`d45f61c`）、社交预览图（`fcf2b79`）

## [1.0.0] - 2026-09-08

首个公开发布版本。

### 新增

- **一键三向切换**：`codex-switch.sh openai|deepseek|kimi` + 三个 `.command` 双击入口，自动完成退出应用 → 写入配置 → 同步会话显示标记 → 改写历史模型名 → 重启应用
- **跨供应商续聊自动化**：
  - 模型名改写：解决续聊 pre-sampling compact 钉死会话元数据模型名导致的 `invalid_request_error`
  - 第三方历史残留清理：切回官方时自动处理 reasoning 残留字段
  - 所有改写/清理前自动留首次备份（`.bak-model` / `.bak-reasoning` / `.bak-switch`）
- **Kimi 本地路由**：codeproxy（8787）+ launchd 常驻服务
- **模型目录分家**：DeepSeek / Kimi 各用独立模型目录，GUI 模型选择器只显示当前供应商的模型，杜绝错选
- **CC Switch 可选集成**：已安装则自动同步其「使用中」标记（仅面板展示，不依赖）

[Unreleased]: https://github.com/aipmer/codex-switch/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/aipmer/codex-switch/releases/tag/v1.0.0
