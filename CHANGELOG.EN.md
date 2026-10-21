# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

[中文](docs/Changelog.md)

## [Unreleased]

## [1.5.2] - 2026-10-21

### Fixed

- **trim now swaps base64 images inside the protected zone too**: the recent working zone (last 2MB by default) was previously left fully untouched, but large screenshots from UI-snapshot tools (measured: a single 2.3MB image) inside the zone still pushed the request body past third-party gateway nginx limits (kimi mode failed continuations with `413 Payload Too Large`). The zone now protects text only; images are always swapped for the 1x1 placeholder (measured: a 21.4MB active work session trimmed to 1.2MB, resumable in kimi mode again)

## [1.5.1] - 2026-10-21

### Fixed

- **trim now covers base64 screenshots embedded in tool-output lists**: UI-snapshot tools embed screenshots as `input_image` (data: URLs) inside the `output` list of `custom_tool_call_output` / `function_call_output` and in MCP result `content` lists — a single one can reach 1.6MB. v1.5.0 only handled images in message content and missed these. They are now swapped for the 1x1 placeholder as well (measured: an active 8.5MB work session shed another 4.2MB thanks to this)

## [1.5.0] - 2026-10-21

### Added

- **Smart trimming of giant sessions (`trim-rollout-output.py`)**: long-running sessions fail to resume with `Your input exceeds the context window of this model` — the app replays the full history to the model, and the bulk is not conversation text but accumulated tool output (image-generation base64, MCP tool output, command output, pasted base64 images, and the `guardian_history` audit copy inside compacted window records). The tool trims only old tool outputs and pasted bulk; user/assistant message text is never touched. Base64 images are swapped for a 1x1 placeholder PNG (keeps structure valid), oversized text keeps a 500-char head plus a placeholder note, and the last 2MB "recent working zone" is left untouched (compacted window records excepted). The original is backed up as `.bak-trim-<timestamp>` and the projection caches of affected threads (including forks) are invalidated. Measured: a 20.8MB session trimmed to 7.6MB, replay payload (latest window + tail) down from ~2.7MB to ~181KB. Usage: `python3 trim-rollout-output.py <rollout.jsonl> [--keep-recent-mb 2] [--max-field-chars 4000] [--max-msg-chars 20000]` — always run `remap-history-base.py` afterwards to repair fork offsets

### Fixed

- **remap now supports `.jsonl.zst` compressed fork sources**: app 0.163.x validates lineage offsets against the **compressed byte size**, while `history_base.end_byte_offset` records decompressed offsets — any source compressed by the maintenance task inevitably fails validation, showing as repeated reconnects and an "cannot open file" tab error. `.zst` candidate sources are now decompressed back to `.jsonl` before offset calculation (the original is renamed to `.zst.bak-lineage` and excluded from scans), self-healing on the next run if the app re-compresses them. Also adds reading compressed sources (`zstd -dc`, offsets measured on decompressed bytes) and a "next surviving line / end of file" fallback when the target ordinal was deleted by cleanup

## [1.4.0] - 2026-09-18

### Added

- **Default-model presets**: no need to re-pick a model in the UI after switching — openai→`gpt-5.6-terra`, kimi→`k3-256k`, deepseek→`deepseek-v4-flash`, all at medium reasoning effort. Besides the new-session defaults in the config templates, the switch script also flips the pinned `model` / `reasoning_effort` of every thread in `state_5.sqlite`'s `threads` table — otherwise reopening an old conversation still runs on the old model and fails. Adjust `DEF_MODEL` in the script and the `model` field in each config template as needed

## [1.3.0] - 2026-09-18

### Added

- **Forked-session `history_base` offset remapping (`remap-history-base.py`)**: a forked session file embeds `history_base.end_byte_offset` in its header, pointing at a byte position in the source rollout file. After history rewriting changes the source's length, the offset falls past the end and the app fails with `invalid paginated history lineage: cutoff byte offset is past the source rollout` — the conversation won't open, and projection-cache invalidation can't help because the offset lives in the jsonl, not the database. The new script relocates the same line via `end_ordinal_exclusive` in the source file and updates the cutoff to its current byte offset; supports multi-level fork chains, idempotent, auto-invalidates affected threads' projection caches. Runs automatically on every switch; standalone repair: `python3 remap-history-base.py ~/.codex`

### Changed

- **Incremental + streaming history rewrites**: the model-name rewrite and third-party residue cleanup passes each keep their own processed-timestamp (`~/.codex/.switch-rewrite-marker-model` / `-reasoning`) and only scan files modified since the last run (archived sessions are processed once and skipped forever); all I/O is line-by-line streaming — files are never loaded whole into memory, and unchanged files are read-only. Switch time no longer grows with session history (tested against a 14 GB / 448-file library with a 464 MB single file). The first switch after upgrading performs one final full scan to establish the baseline

## [1.2.0] - 2026-09-11

### Added

- **Browser control in third-party mode**: Codex's embedded browser / Computer Use is an OpenAI cloud service and always fails with `Codex auth token is unavailable` in third-party mode. Two new bridges based on Kimi WebBridge let Codex drive the user's real browser (with login sessions):
  - `skills/webbridge-browser/SKILL.md` (recommended): teaches Codex to call the WebBridge daemon via `exec_command` curl — verified end-to-end
  - `webbridge-mcp.py` (fallback): an MCP stdio bridge. Note Codex 0.153.4 hardcodes `tool_search_always_defer_mcp_tools` to true, so MCP tools are invisible in exec mode and only surfaced via the GUI's tool_suggest

## [1.1.0] - 2026-09-10

### Fixed

- **GUI projection-cache invalidation (2026-09-09)**: the Codex GUI reads conversations from a projection in `thread_history_1.sqlite` that indexes rollout files by byte offset. In-place rewrites invalidated those offsets, leaving the GUI stuck showing stale content. The script now invalidates the affected threads' projection rows after any rewrite/cleanup; the app rebuilds them from the jsonl on next launch. (`4cae38c`)
- **Four-layer official-API validation on resume (2026-09-08/09)**: history items produced by third-party direct `/responses` endpoints trip four consecutive validations — reasoning `content` array (`array_above_max_length`), locally Fernet-encrypted `encrypted_content` (`invalid_encrypted_content`), `tool_`-prefixed tool-call ids (`invalid_id_prefix`), and third-party `rs_` reasoning ids (`Item with id 'rs_...' not found`). On switching to openai, the script strips reasoning content/encrypted_content/id and rewrites tool-call ids to the `fc` prefix; resume verified working. (`15538dc`)
- **Kimi schema validation (2026-09-08)**: added the port-8788 schema shim fixing MCP tool schemas (`$ref` + sibling `type`) rejected by Kimi's validator (`moonshot flavored json schema`); both K3 and K2.7 verified returning 200. (`e6505f7`)

### Documentation

- **Bidirectional resume test results (2026-09-08)**: README now documents the full forward/reverse cross-provider resume findings, the four validation symptoms layer by layer, and the cleanup trade-offs
- **Troubleshooting table extended (2026-09-09)**: new entries for "conversation shows stale content" and "threads disappear from the list after switching", with self-check commands for config vs `state_5.sqlite` flag consistency
- **CC Switch role clarified (2026-09-07)**: verified on CC Switch v3.19.2 / v3.20.1 (including takeover mode) that clicking "enable" never writes `~/.codex/config.toml`; docs now state it is a read-only panel and real switching must go through the script
- Added English README (`3285b92`), badges (`d45f61c`), and social preview image (`fcf2b79`)

## [1.0.0] - 2026-09-08

First public release.

### Added

- **One-click three-way switching**: `codex-switch.sh openai|deepseek|kimi` plus three double-clickable `.command` entries — quit app → write config → sync session visibility flags → rewrite historical model names → relaunch
- **Automated cross-provider resume**:
  - Model-name rewriting: fixes `invalid_request_error` caused by pre-sampling compaction pinning the model name recorded in session metadata
  - Third-party residue cleanup: handles reasoning residue fields when switching back to official mode
  - First-touch backups before every rewrite/cleanup (`.bak-model` / `.bak-reasoning` / `.bak-switch`)
- **Kimi local routing**: codeproxy (port 8787) running as a launchd service
- **Split model catalogs**: separate catalogs for DeepSeek and Kimi so the GUI model picker only shows the active provider's models
- **Optional CC Switch integration**: syncs its "in use" flag when installed (panel display only, not required)

[Unreleased]: https://github.com/aipmer/codex-switch/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/aipmer/codex-switch/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/aipmer/codex-switch/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/aipmer/codex-switch/releases/tag/v1.0.0
