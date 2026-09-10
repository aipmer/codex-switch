# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

[中文](CHANGELOG.md)

## [Unreleased]

### Fixed

- **GUI projection-cache invalidation**: the Codex GUI reads conversations from a projection in `thread_history_1.sqlite` that indexes rollout files by byte offset. In-place rewrites invalidated those offsets, leaving the GUI stuck showing stale content. The script now invalidates the affected threads' projection rows after any rewrite/cleanup; the app rebuilds them from the jsonl on next launch. (`4cae38c`)
- **Four-layer official-API validation on resume**: history items produced by third-party direct `/responses` endpoints trip four consecutive validations — reasoning `content` array (`array_above_max_length`), locally Fernet-encrypted `encrypted_content` (`invalid_encrypted_content`), `tool_`-prefixed tool-call ids (`invalid_id_prefix`), and third-party `rs_` reasoning ids (`Item with id 'rs_...' not found`). On switching to openai, the script strips reasoning content/encrypted_content/id and rewrites tool-call ids to the `fc` prefix; resume verified working. (`15538dc`)
- **Kimi schema validation**: added the port-8788 schema shim fixing MCP tool schemas (`$ref` + sibling `type`) rejected by Kimi's validator (`moonshot flavored json schema`); both K3 and K2.7 verified returning 200. (`e6505f7`)

### Documentation

- Added English README (`3285b92`), badges (`d45f61c`), and social preview image (`fcf2b79`)
- Troubleshooting table extended: four-layer validation symptoms, GUI projection cache, and self-check commands for provider-flag mismatch

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

[Unreleased]: https://github.com/aipmer/codex-switch/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/aipmer/codex-switch/releases/tag/v1.0.0
