# 更新日志

本项目的所有重要变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

[English](../CHANGELOG.EN.md)

## [Unreleased]

## [1.5.2] - 2026-10-21

### Fixed

- **trim 保护区内也换 base64 图片**：最近工作区（默认尾部 2MB）此前完全不动，但 UI 快照工具产生的大截图（实测单张 2.3MB）落在保护区内时，请求体仍会超第三方网关 nginx 上限（kimi 模式续聊报 `413 Payload Too Large`）。现在保护区只保护文字，图片一律换 1x1 占位图（实测一个 21.4MB 的活跃工作会话剪到 1.2MB，kimi 模式恢复可续聊）

## [1.5.1] - 2026-10-21

### Fixed

- **trim 覆盖工具输出列表内嵌的 base64 截图**：UI 快照类工具会把截图以 `input_image`（data: URL）形式混在 `custom_tool_call_output` / `function_call_output` 的 `output` 列表与 MCP 结果 `content` 列表里，单张可达 1.6MB；v1.5.0 只处理消息 content 里的图片，遗漏了这类。现在一并换 1x1 占位图（实测一个 8.5MB 的活跃工作会话因此多剪掉 4.2MB）

## [1.5.0] - 2026-10-21

### Added

- **巨型会话智能修剪（`trim-rollout-output.py`）**：长期使用的会话续聊时报 `Your input exceeds the context window of this model`——App 把全量历史回放给模型，体积大头不是对话文字而是历年的工具输出（图像生成 base64、MCP 工具输出、命令回显、粘贴的 base64 图片、compacted 窗口记录里的 `guardian_history` 审查副本）。本工具只裁旧工具输出与粘贴大文件，user/assistant 消息文字一律不动；base64 图片换 1x1 占位 PNG 保持结构合法，超长文本保留开头 500 字符加占位说明，文件尾部 2MB 最近工作区不动（compacted 窗口记录除外），原文件自动备份 `.bak-trim-<时间戳>` 并失效相关线程（含分叉）投影缓存。实测 20.8MB 会话剪到 7.6MB，回放负载（最新窗口+尾部）从 ~2.7MB 降到 ~181KB。用法：`python3 trim-rollout-output.py <rollout.jsonl> [--keep-recent-mb 2] [--max-field-chars 4000] [--max-msg-chars 20000]`，运行后必须再跑 `remap-history-base.py` 修复分叉偏移

### Fixed

- **remap 兼容 `.jsonl.zst` 压缩分叉源**：App 0.163.x 对压缩源按**压缩后字节数**校验 lineage 偏移，而 `history_base.end_byte_offset` 记录的是解压后偏移——源一旦被维护任务压成 `.zst` 必然越界，症状为打开会话反复重新连接、标签页提示无法打开文件。现在候选源为 `.zst` 时先解压回 `.jsonl` 再计算偏移（原文件改名 `.zst.bak-lineage` 留档不再参与扫描），App 再次压缩则下次运行自动自愈；同时支持读取压缩源（`zstd -dc`，偏移按解压后字节计）与目标 ordinal 已被清理删除时的「下一个幸存行/文件末尾」回退

## [1.4.0] - 2026-09-18

### Added

- **默认模型预设**：切换后无需在界面重新选择模型——openai→`gpt-5.6-terra`、kimi→`k3-256k`、deepseek→`deepseek-v4-flash`，强度统一 medium。除 config 模板的新会话默认值外，切换脚本还会翻转 `state_5.sqlite` 的 `threads` 表中每个会话钉死的 `model` / `reasoning_effort`，否则打开旧会话仍用旧模型执行失败。可按需修改脚本里的 `DEF_MODEL` 与各 config 模板的 `model` 字段

## [1.3.0] - 2026-09-18

### Added

- **分叉会话 `history_base` 偏移重映射（`remap-history-base.py`）**：分叉会话文件头内嵌的 `history_base.end_byte_offset` 指向源 rollout 文件的字节位置；历史改写改变源文件长度后偏移越界，App 报 `invalid paginated history lineage: cutoff byte offset is past the source rollout`、对话无法打开（偏移在 jsonl 里而非数据库，失效投影缓存无法解决）。新脚本按 `end_ordinal_exclusive` 在源文件中重新定位同一行并把 cutoff 更新为当前字节偏移，支持多级分叉链，幂等可反复运行，修复后自动失效对应线程的投影缓存。每次切换自动调用，也可独立运行：`python3 remap-history-base.py ~/.codex`

### Changed

- **历史改写改为增量 + 流式**：模型名改写与第三方残留清理各记录独立的处理时间戳（`~/.codex/.switch-rewrite-marker-model` / `-reasoning`），只扫描上次处理后变动过的文件（归档会话处理一次即永久跳过）；全程逐行流式读写，不再把整个文件读进内存，无改动的文件只读不写。切换耗时不再随会话积累增长（实测 14 GB / 448 个文件、单文件最大 464 MB 的会话库）。升级后首次切换会做最后一次全量扫描建立基线

## [1.2.0] - 2026-09-11

### 新增

- **第三方模式的浏览器控制**：Codex 内嵌浏览器 / Computer Use 是 OpenAI 云端服务，第三方模式下必然报 `Codex auth token is unavailable`。新增两种基于 Kimi WebBridge 的桥接，让 Codex 在第三方模式下操作用户真实浏览器（自带登录态）：
  - `skills/webbridge-browser/SKILL.md`（推荐主路径）：教 Codex 用 `exec_command` curl 调用 WebBridge 守护进程，实测全链路通过
  - `webbridge-mcp.py`（备用）：MCP stdio 桥接服务。注意 Codex 0.153.4 将 `tool_search_always_defer_mcp_tools` 硬编码为 true，MCP 工具在 exec 模式下不可见，仅供 GUI 的 tool_suggest 发现

## [1.1.0] - 2026-09-10

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

[Unreleased]: https://github.com/aipmer/codex-switch/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/aipmer/codex-switch/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/aipmer/codex-switch/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/aipmer/codex-switch/releases/tag/v1.0.0
