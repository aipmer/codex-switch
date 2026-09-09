# codex-switch

[中文文档](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey.svg)]()
[![Shell](https://img.shields.io/badge/shell-bash-4EAA25.svg)]()
[![Codex](https://img.shields.io/badge/tested-Codex%200.153.4-blue.svg)]()


One-click provider switching for Codex (the CLI bundled with the ChatGPT desktop app) on macOS: switch instantly between **OpenAI official** (ChatGPT subscription), **DeepSeek**, and **Kimi Code** — with **seamless cross-provider conversation resume**.

Built for a real workflow: when your GPT quota runs out or expires, fall back to a third-party model; when quota resets, switch back — **old conversations continue in both directions**, no new windows, no re-explaining context.

> All findings verified by hands-on testing on Codex 0.153.4 + CC Switch 3.20.1 (Sep 2026), not speculation.

## Features

- One-click switch: quit Codex app → write config → sync session visibility flags → relaunch
- **Automated cross-provider resume** (the core value — two empirically discovered pitfalls, both handled):
  1. **Model-name rewriting**: on resume, codex's pre-sampling compaction pins the model name recorded in the session metadata, ignoring your current config. Cross-provider resumes get rejected with `invalid_request_error`. On every switch, the script batch-rewrites `"model":"..."` in all historical rollout files to the target provider's model name.
  2. **Third-party residue cleanup** (only when switching to OpenAI): history items produced by a third-party direct `/responses` endpoint trip four official-API validations — a reasoning `content` array (`array_above_max_length`), a locally Fernet-encrypted `encrypted_content` (`invalid_encrypted_content`), a third-party `rs_` reasoning id (`Item with id 'rs_...' not found`, since the official store=false has no record), and `tool_`-prefixed tool-call ids (`invalid_id_prefix`; the official API requires `fc`). When switching to openai, the script recursively strips reasoning content/encrypted_content/id and rewrites tool-call id prefixes to `fc` (including items nested in `compacted` payloads); OpenAI receives summaries only and resume works.
  3. **GUI projection-cache invalidation**: the Codex GUI reads conversations from a projection in `thread_history_1.sqlite` that indexes rollout files by byte offset. In-place rewrites invalidate those offsets, leaving the GUI stuck showing stale content. After any rewrite/cleanup, the script deletes the affected threads' projection rows; the app rebuilds them from the jsonl on next launch.
- First-touch backups before any rewrite/cleanup (`.bak-model` / `.bak-reasoning` / `.bak-switch`)
- If CC Switch is installed, its "in use" flag is synced automatically (panel display only)

## Why not just CC Switch

Clicking "Enable" in CC Switch **only flips a flag in its own database — it does not write Codex's actual config**. Verified on v3.19.2 (issue #6236) and v3.20.1 (both takeover and normal modes): the log says "taken over" while `~/.codex/config.toml`'s mtime never changes. CC Switch is fine as a config vault and usage panel; real switching requires this script.

## Installation

```bash
git clone https://github.com/aipmer/codex-switch.git
cd codex-switch
chmod +x codex-switch.sh *.command codeproxy-kimi.sh
```

1. Edit `config-deepseek.toml`, replace `YOUR_DEEPSEEK_API_KEY` with your key
2. For Kimi, set up the local proxy first (next section)
3. Run `./codex-switch.sh openai|deepseek|kimi`, or double-click a `.command`

## Kimi local proxy (codeproxy)

Recent Codex versions only speak the Responses API and forcibly attach a `tool_search` tool, which Kimi's `/responses` endpoint rejects: `invalid_request_error: tool type "tool_search" is not supported`. The official workaround is a local proxy (<https://www.kimi.com/zh-hans/resources/codex-api>):

1. Install codeproxy per the Kimi Code docs: <https://www.kimi.com/code/docs/>
2. Edit `codeproxy-kimi.sh`, replace `YOUR_KIMI_API_KEY`, copy it to `~/.codex/` (launchd may not have access to Documents etc.)
3. Edit `com.codexswitch.codeproxy-kimi.plist`, replace both `REPLACE_WITH_HOME` with your absolute home path, copy to `~/Library/LaunchAgents/`
4. Load: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.codexswitch.codeproxy-kimi.plist`
5. Codex Desktop's built-in MCP tool schemas are rejected by Kimi's validator (`moonshot flavored json schema` error), so a schema shim is also required: copy `schema-shim-kimi.py` to `~/.codex/`, edit the two `REPLACE_WITH_*` placeholders in `com.codexswitch.schema-shim-kimi.plist`, install it under LaunchAgents and bootstrap. The chain is Codex → shim(8788) → codeproxy(8787) → Kimi; `config-kimi.toml`'s `base_url` points at 8788

After that, `codex-switch.sh kimi` ensures the proxy is running automatically.

## Split model catalogs (optional but recommended)

If both third-party configs share one model catalog (`model_catalog_json`), Codex's model picker lists everyone's models — picking a Kimi model in DeepSeek mode gets rejected by the API. Split the catalog per provider so DeepSeek mode shows only `deepseek-v4-flash / deepseek-v4-pro` and Kimi mode shows only Kimi models.

Generate a catalog from `codex debug models` output, split it per provider, and point `model_catalog_json` in `config-deepseek.toml` / `config-kimi.toml` at the respective files.

## Caveats

- **Switching overwrites `~/.codex/config.toml` entirely**: merge your trusted projects, plugins, notify hooks etc. into the three templates in this repo, or they will be lost on switch
- Rewriting applies at switch time; sessions created afterwards already carry the current model name
- Switching back and forth rewrites model names both ways (e.g. gpt-5.6-luna → deepseek-v4-flash → gpt-5.6-sol) — attribution precision degrades but functionality is unaffected; originals live in `.bak-model`
- Stripped reasoning text is unrecoverable (originals in `.bak-reasoning`); when switching back to third-party, those reasoning items carry empty summaries — DeepSeek/Kimi tolerate this in testing
- Archived sessions need `codex unarchive <session-id>` before resuming

## Troubleshooting

| Symptom | Check |
| --- | --- |
| kimi mode: Connection refused | `launchctl print gui/$(id -u)/com.codexswitch.codeproxy-kimi`; `tail ~/.codex/codeproxy-kimi.log`; restart with `launchctl kickstart -k gui/$(id -u)/com.codexswitch.codeproxy-kimi` |
| kimi mode: 401 | Key expired — regenerate in the Kimi Code console, update `--apikey` in `~/.codex/codeproxy-kimi.sh`, kickstart |
| kimi mode: `not a valid moonshot flavored json schema` | Config bypassed the shim (8788) and hit codeproxy (8787) directly — check `base_url` |
| kimi mode: tool_search not supported | Config bypasses the proxy — check `base_url = "http://127.0.0.1:8787/v1"` in `~/.codex/config.toml` |
| History sessions invisible after switch | Provider flags out of sync — just re-run the switch script |
| Conversation shows stale content after switch (latest messages missing) | The GUI's projection cache (`thread_history_1.sqlite`) indexes rollout files by byte offset; in-place rewrites invalidate it — the script now auto-invalidates projections for rewritten threads; with older versions, delete that thread's projection rows (or clear the tables) and restart the app — it rebuilds from the jsonl, which is never touched destructively |
| Official mode resume fails with `array_above_max_length` / `invalid_encrypted_content` / `invalid_id_prefix` / `Item with id 'rs_...' not found` | Third-party history residue (reasoning content/encrypted_content/rs_ id, `tool_`-prefixed tool-call ids) — auto-cleaned on switch to openai; if it persists, the session was created after the switch, re-run the script |
| Third-party resume of official session fails with `passed gpt-5.x` | Session model names not rewritten — re-run the switch script |
| Picker shows another provider's models | Catalogs not split — see "Split model catalogs" |
| Verify proxy health | `curl -s http://127.0.0.1:8787/v1/responses -H "Content-Type: application/json" -d '{"model":"kimi-for-coding","input":"hi","stream":false}'` |

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `CODEX_HOME` | `~/.codex` | Codex config directory |
| `CODEX_SWITCH_APP` | `ChatGPT` | Desktop app name |
| `CODEX_SWITCH_CLI` | `/Applications/ChatGPT.app/Contents/Resources/codex` | CLI path (version display) |
| `CODEX_SWITCH_LAUNCHD_LABEL` | `com.codexswitch.codeproxy-kimi` | launchd label for the Kimi proxy |

## Files

- `codex-switch.sh` — main switch script
- `config-openai.toml` / `config-deepseek.toml` / `config-kimi.toml` — config templates
- `切换到*.command` — double-click launchers
- `codeproxy-kimi.sh` + `com.codexswitch.codeproxy-kimi.plist` — Kimi local proxy templates
- `schema-shim-kimi.py` + `com.codexswitch.schema-shim-kimi.plist` — Kimi schema shim templates

## License

MIT
