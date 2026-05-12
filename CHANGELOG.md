# Changelog

All notable changes to claude-session-logger will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — v0.3.7 work in progress

### Added (Phase 4 — session marker broadcast, Closes #39)
- **Session-start and compaction markers now broadcast to every enabled channel** (#39): the `═══ SESSION START` and `═══ CONTEXT COMPACTED` rules previously appeared only in `.shell_*` and `.sesslog_*`. Phase 4 broadcasts them to all enabled top-level channels (`.tools_*`, `.convo_*`, `.unknowns_*`, `.tasks_*`, opt-in `.fileio_*`) so each channel file is self-contained for run/compaction boundaries when read in isolation.
- **`ChannelOptions.suppress_markers: bool` opt-out per channel** (#39): set on any channel to keep its log files marker-free without disabling the channel itself. Default is `False` (markers visible) for every shipped channel. The field was wired through Phase 1's data model; Phase 4 makes it consequential.
- **`SessionLogger._collect_marker_target_paths()`** (#39): new helper that resolves the broadcast target list. Iterates only top-level declared channels in `routing.channels` (subtype-derived `.bash-powershell_*` / `.convo-help_*` files are deliberately excluded — they materialize lazily on first matching tool call and may not exist at marker time; keeping them clean is the documented policy).
- **Run/compaction counter authority stays on sesslog** (#39): `get_run_number` and `count_compaction_markers` continue to read from `self.unified_log_path` regardless of how many channels the broadcast touched. Broadcasting to N channels does not inflate the next run number — the sesslog is the single source of truth.
- **8 new pytest tests** in `tests/one-offs/test_marker_broadcast.py` (#39) across 4 sections: broadcast covers all enabled channels by default; `suppress_markers=True` opts a channel out; disabled channels (including default-disabled `.fileio_*`) receive no markers; subtype-derived channels stay clean; run counter reads sesslog even when broadcast wrote markers elsewhere; disabling sesslog documents the known limitation (counter floors at 1).

### Notes (Phase 4)
- **Snapshot baseline re-captured.** The Phase 4 deltas are additive — markers in 4 additional channel files (`.convo_*`, `.tasks_*`, `.tools_*`, `.unknowns_*`) plus 4 new files in the subagent session directory (subagent SessionStart now broadcasts the same way). Pre-Phase-4 byte content of shell/sesslog channels is preserved verbatim. Old baseline preserved at `tests/snapshots/v036_baseline_pre_phase4/` for historical reference.
- **Total tests: 210** (101 Phase 0 + 45 Phase 1 + 56 Phase 2+3 + 8 Phase 4).

### Added (Phase 2+3 — LogEntry/formatter cutover)
- **`cclogger/formatters/` package** (#38): `formatters.py` is now a package with `legacy.py` (relocated v0.3.6 helpers — get_command_content, generate_entry, format_datetime, etc.), `base.py` (`BaseFormatter` ABC with shared verbosity/newline/role-label resolution helpers), `default.py` (`DefaultFormatter` — the v0.3.6 hybrid-json `{ROLE: "preview"}` shape), `chat.py` (`ChatFormatter` — multi-line readable shape for the convo channel), `task_only.py` (`TaskOnlyFormatter` — replaces the v0.3.6 hardcoded `if channel_name == "tasks"` branch). Existing imports continue to work via `__init__.py` re-exports; new code should import from submodules directly.
- **`format_for_channel(entry, channel_opts, channel_name, config)` dispatch** in `cclogger/formatters/__init__.py` (#38): single per-channel formatting entry point. Resolves the formatter class from `ChannelOptions.formatter` (default `"default"`), instantiates it with channel context, and returns the formatted string. Unknown formatter names fall back to `DefaultFormatter` with a debug-log warning.
- **`CommandContent` dataclass** in `cclogger/models.py` (#38): three fields — `raw_content` (full content for snippet substitution), `legacy_string` (v0.3.6 pre-truncated preview), `summary_template` (rich-format template with `{snippet}` placeholder, None for non-rich handlers). Returned by the new `get_command_content_structured()`. Lets per-channel verbosity actually apply to Edit/Write rich-format snippets.
- **Per-channel default `ChannelOptions`** baked into `_default_channels()` in `models.py` (#38): `convo` uses `formatter="chat"` + `NewlinePolicy.RENDER` + `verbosity="full"` (multi-line conversation rendering); `sesslog` uses `verbosity="full"` (kitchen-sink channel never truncates); `tasks` uses `formatter="task-only"` (replaces hardcoded dispatch); `shell`/`tools`/`unknowns` use `verbosity={"max_chars": 100}` (bumped from global default of 20 — shell-style entries deserve more room).
- **`_warn_unknown_role_once()`** in `cclogger/debug.py` (#38): mirrors the v0.2.1 unknown-tool throttled-warning pattern with a sibling sentinel directory (`~/.claude/logs/.unknown_role_warnings/`). Triggered when a `LogEntry.role` falls outside the closed `ROLES` enum — formatters render the role as `??:<role>` in logs AND emit a one-time debug-log warning so we can extend ROLES when novel roles appear in real traffic.
- **Subtype-channel options inheritance** (#38): subtype-derived channels (e.g., `.shell-powershell_*`, `.tools-github_*`, `.convo-help_*` — created dynamically when `subtype_routing.<category>` is enabled) now inherit their base channel's `ChannelOptions` instead of silently falling back to global defaults. Standard inheritance pattern: declare-to-override (explicitly add a subtype channel to `routing.channels` to give it custom options), omit-to-inherit (most users — the derived channel uses parent's verbosity, formatter, newline_policy, etc.). Without this, enabling `subtype_routing.tools = true` would write `.tools-github_*.log` with 20-char snippets even though the parent `.tools_*.log` uses 100-char snippets per its bundled options. New helper `SessionLogger._resolve_channel_options(channel, channel_name)` encapsulates the lookup. 7 new tests pin the inheritance contract.
- **`_default` reserved keyword in per-role verbosity dicts** (#38): framework-completeness extension. Lets a channel express "default = X, but override these specific roles" — e.g., `{"_default": "full", "write": {"max_chars": 20}}` means "full for everything, except Write at 20 chars." Without this keyword, unmatched roles in a per-role dict fell to the global default (20), preventing channels from setting a meaningful channel-level fallback. The reserved-key set is now split into two semantic groups: `HINT_VERBOSITY_KEYS = {"max_chars", "max_lines"}` (describe a single value when used alone) and `PER_ROLE_RESERVED_KEYS = {"_default"}` (per-role-dict fallback that coexists with role keys). `_resolve_verbosity` and `_resolve_newline_policy` both consult `_default` at the per-role-dict fallback step. 7 new tests pin the resolution behavior, hint-vs-role classification, and the newline_policy parallel.
- **`.fileio_*` channel — opt-in full file-I/O capture** (#38): new channel (disabled by default) that captures Read/Write/Edit/MultiEdit/NotebookEdit entries with full content using `formatter="default"`, `verbosity="full"`, and `newline_policy=RENDER` for diff-readable multi-line rendering. Enable by setting `routing.channels.fileio.enabled = true`. Companion to the sesslog truncation fix below: most users don't want full file content cluttering the kitchen-sink sesslog channel, but some workflows (auditing file mutation sequences, capturing diffs for postmortems) want it captured to disk. The transcript JSONL already has the full content; `.fileio_*` makes it available at log-level granularity. 6 new tests verify channel defaults, disabled state, routing, and Read recategorization.
- **`io` category route includes `fileio`** (#38): the `io` category (Write/Edit/MultiEdit/NotebookEdit/Read) now routes to `[shell, sesslog, tools, fileio]` by default. `fileio` being disabled by default means no log files appear unless explicitly enabled.
- **sesslog default truncates file-I/O entries** (#38): regression fix using the new `_default` keyword. sesslog's bundled `ChannelOptions(verbosity={"_default": "full", "write": {"max_chars": 20}, "edit": {"max_chars": 20}, "multi-edit": {"max_chars": 20}, "notebook-edit": {"max_chars": 20}})` keeps conversation prose and tool calls at full verbosity while truncating file-content entries — matching v0.3.6 sesslog readability for Write/Edit while preserving Phase 2+3's full-prose-on-sesslog improvement.

### Changed (Phase 2+3 framework completeness)
- **Read moved from `system` to `io` category** (#38): Phase 2+3 makes Read semantically a file-I/O operation alongside Write/Edit/MultiEdit/NotebookEdit. Read entries now route to the same channels as Write/Edit, including the new opt-in `.fileio_*`. `system` category now contains plan modes only (EnterPlanMode/ExitPlanMode), which have no content to capture. Users with customized `routing.category_routes.system` will see Read no longer routed via that key.
- **56 new pytest tests** in `tests/one-offs/test_channel_options.py` (#38) across 10 new sections (13-22): formatter registry contents, `format_for_channel` dispatch routing, snippet substitution (template path takes precedence over `_legacy_complete` when channel has explicit options), NewlinePolicy round-trip (ESCAPE produces `\n`, RENDER preserves real newlines), per-channel defaults wire through, hardcoded-removal AST regression (no `truncate_preview` calls left in conversation.py, no `if channel_name == "tasks"` dispatch branch in log_entry), `CommandContent` dataclass + `get_command_content_structured` shape, ROLE_LABELS resolution + `??:<role>` fallback for unknown roles + per-channel role_label override longest-prefix walk, subtype-channel options inheritance contract.

### Changed (Phase 2+3)
- **Handlers now emit `LogEntry`** (#38): `generate_entry()` returns a `LogEntry` instance instead of a pre-formatted string. The LogEntry's `summary` carries either the rich-format template (with `{snippet}` placeholder) for handlers that have one (Edit, Write — Skill keeps its own truncation budget via `skill_args_length`) or `None` for non-rich handlers. `metadata['_legacy_complete']` carries the byte-identical legacy string for non-template entries (Bash, ls, Grep, etc.) so default channels stay byte-identical to v0.3.6.
- **`SessionLogger.log_entry()` cut over to formatter dispatch** (#38): the `task_content` parameter is removed — task-tool callers stuff task data into `LogEntry.metadata['task_content']` and the `tasks` channel's `formatter="task-only"` ChannelOptions picks the right formatter via dispatch. The v0.3.6 `if channel_name == "tasks" and task_content:` hardcoded branch is gone; all routing goes through `format_for_channel()`.
- **Conversation handlers emit `LogEntry`** (#38): `conversation.py` (UserPromptSubmit, Stop, SubagentStop) now builds `LogEntry(raw_content=text, role="user"|"ai"|"agent", ...)` instead of pre-formatting strings. The two v0.3.6 hardcoded `truncate_preview(prompt, max_len=200, config=config)` literals are removed — convo channel uses `verbosity="full"` to capture full prose; sesslog also captures full conversation prose; other channels (if user routes prose there) get per-channel verbosity.
- **`get_command_content()` is now a thin wrapper** (#38) over `get_command_content_structured()` that returns just the `legacy_string` field. New callers should use the structured form to access the rich-format template.

### Notes (Phase 2+3)
- **Snapshot baseline re-captured.** Phase 2+3 is the first phase that produces intentional non-byte-identical output. The deltas: convo channel now multi-line readable with full content (was 200-char single-line preview), sesslog channel captures full conversation prose without quote-wrapping (was 200-char single-line with quotes), shell/tools/unknowns channels show 100-char snippets for Edit/Write rich format (was 20-char). Old baseline preserved at `tests/snapshots/v036_baseline_pre_phase23/` for historical reference.
- **Total tests: 202** (101 Phase 0 + 45 Phase 1 + 56 Phase 2+3); `audit_symbol_parity.py` reports the only structural drifts are the intentional `LogEntry` repurpose, `ChannelConfig.options` field addition, and `SessionLogger.log_entry()` losing the `task_content` parameter, plus 20+ net-new symbols (formatter classes, dispatch helpers, `CommandContent`, `_resolve_channel_options`, `HINT_VERBOSITY_KEYS`, `PER_ROLE_RESERVED_KEYS`, `_warn_unknown_role_once`).
- **Per-tool truncate refactor in handlers** (#38, intentional Phase 2+3 scope): the v0.3.6 `truncate_preview()` calls inside the Write/Edit handlers in `formatters/legacy.py:get_command_content` are removed — handlers now return `CommandContent.summary_template` with a `{snippet}` placeholder, and `DefaultFormatter._format_template_entry()` substitutes the placeholder with verbosity-truncated raw_content per channel options. Skill keeps its own pre-truncation (uses the distinct `skill_args_length` budget, default 100 chars, not the global `content_preview_length`).

### Added (Phase 1 — ChannelOptions data model + hierarchical resolution)
- **`NewlinePolicy` enum** in `cclogger/models.py` (#38): two modes — `ESCAPE` (literal `\n` in output, current default behavior) and `RENDER` (actual newlines, multi-line entries). Sub-option of the `default` formatter; `chat`/`xml`/`jsonl` formatters (Phase 2+3) have intrinsic newline behavior. PARAGRAPH was deliberately dropped from the design — was over-engineering from a misread; the original "compact with `\n\n` for grepping" intent is satisfied by the existing `ESCAPE` behavior.
- **`ChannelOptions` dataclass** in `cclogger/models.py` (#38): five fields — `verbosity` (preset string OR hint dict OR per-role map), `formatter` (default `"default"`), `newline_policy`, `role_labels` (per-channel override of global ROLE_LABELS), `suppress_markers` (opt-out for the v0.3.7 marker broadcast in #39).
- **`ChannelConfig.options` field** (#38): every channel now carries a `ChannelOptions` (default `ChannelOptions()`). Backwards-compatible additive — channels without explicit options get default behavior.
- **`LogEntry` repurposed** (#38): was dead code in v0.3.6 (defined but never instantiated). Now the structured contract between handlers (which know what happened) and formatters (which know how to display it). Ten fields cover universal needs (`raw_content`, `role`, `timestamp`), default-formatter rich format (`summary` template with `{snippet}` placeholder), formatter-specific extras (`metadata` dict), and failure diagnostics (`is_failure`, `failure_reason`, `error_output`). Designed as the long-term stable contract — Phase 2+3 and future formatter additions extend behavior without changing this shape.
- **`ROLES` set + `ROLE_LABELS` dict** in `cclogger/models.py` (#38): closed enum of role identifiers handlers emit (29 entries spanning conversation roles + all tool categories), with display labels matching current convention (USER/AI/AGENT for prose, TitleCase for tools). Hierarchical with `:` separator for sub-roles (`agent:user`, `agent:senior-engineer:ai`, `bash:powershell`).
- **`RESERVED_VERBOSITY_KEYS` set** in `cclogger/models.py` (#38): `{"max_chars", "max_lines"}` — discriminates a hint-dict from a per-role map and rejects role-name collisions at config load time.
- **5-level hierarchical resolution helpers** in `cclogger/formatters.py` (#38): `_role_prefix_chain(role)` walks `:`-separated path most-specific-first; `_resolve_verbosity(channel_opts, role, tool_name, global_default)` returns effective max-char count via 5-level walk (per-tool override → per-role longest-prefix → channel default → global); `_resolve_newline_policy()` with the same shape returns NewlinePolicy. The pinned edge case (`role="agent:senior-engineer:user"` against `{"agent": "full", "agent:user": "preview"}` → "agent" wins because `agent:user` is NOT a `:`-segment prefix of `agent:senior-engineer:user`) is enforced.
- **Reserved-keyword validation** in `cclogger/config.py` (#38): `_validate_verbosity_dict()` flags mixed reserved-keys + role-keys at config load (logs warning + drops bogus reserved keys); `_build_channel_options()` constructs `ChannelOptions` from JSON with shape validation. Wired into both `_load_per_channel_dir()` (per-channel directory layout) and `_apply_new_config()` (single-file layout).
- **45 new pytest tests** in `tests/one-offs/test_channel_options.py` (#38) across 12 sections proving every pinned design decision with concrete inputs/outputs: data model shape, ChannelOptions defaults, ChannelConfig.options field, LogEntry repurpose, reserved-keyword discriminator, ROLES/ROLE_LABELS, role prefix chain walk, 5-level hierarchical resolution (including the pinned edge case), NewlinePolicy resolution, ConfigLoader integration, reserved-keyword validation, Phase 1 inertness gate.

### Notes (Phase 1)
- **Behavior is unchanged.** Phase 1 fields are inert at runtime — handlers don't yet emit `LogEntry`, formatters don't yet dispatch on `ChannelOptions`. Phase 2+3 wires them in. Total tests: 146 (101 Phase 0 + 45 Phase 1); `diff_check.py` reports byte-identical output against the v0.3.6 baseline (8 log files); `audit_symbol_parity.py` reports the only structural drift is the intentional `LogEntry` repurpose + `ChannelConfig.options` addition.
- **Design decisions** are pinned in `private/claude/2026-05-09__23-01-19__channel-options-framework-pin-design-decisions.md` — captures the user's verbatim responses to ten open design points and synthesizes them into binding decisions.

### Added (Phase 0b — subtractive modularization)
- **`hooks/scripts/cclogger/` package populated with 13 focused modules** (#37): `debug.py` (logging + dazzle-filekit auto-install + unknown-tool warning throttle), `models.py` (dataclasses: `ToolInfo`, `Config`, `ChannelConfig`, `RoutingConfig`, `PerformanceConfig`, `SessionContext`, `LogEntry`), `categorize.py` (`TOOL_CATEGORIES` + subtype extractors), `session_naming.py` (auto-name from cwd + filesystem sanitization), `session_state.py` (state JSON persistence + transcript symlink + shell-type detection), `config.py` (legacy + per-channel directory loading), `formatters.py` (filtering + content extraction + entry generation), `file_io.py` (atomic append + time-gap detection + overflow), `reconciliation.py` (directory + filename rename for `/rename` mid-session), `markers.py` (SESSION-START + CONTEXT-COMPACTED markers + run-counter), `logger.py` (`SessionLogger` with channel routing + subtype expansion), `failure_detection.py` (Bash failure capture), `conversation.py` (USER/AI/AGENT capture via cursor-based transcript reader). Total ~3214 LOC across the package vs 3199 in the original monolith — modest growth from added module docstrings + cross-module imports.
- **`hooks/scripts/cclogger/__init__.py` re-export shim** (#37): runs `_ensure_dazzle_filekit()` once at package-init so downstream `from dazzle_filekit import ...` calls succeed, and re-exports the 14 public + 9 private symbols tests reach via `importlib.import_module("cclogger")`. Backwards-compatible attribute access for tests; new code should import directly from home modules.
- **`tests/one-offs/conftest.py`** (#37): shared `isolate_cursor_state` fixture extracted from inline use in `test_conversation_channels.py`. Also adds `hooks/scripts/` to `sys.path` so any test file can `import cclogger` without per-file boilerplate.
- **`tests/one-offs/audits/audit_symbol_parity.py`** (#37): structural verification tool — AST-parses a baseline `log-command.py` from git (default `v0.3.6` ref) and the union of `cclogger/*.py` + `log-command.py`, then diffs every top-level function signature, class (with methods + dataclass fields), and module-level constant. Reports parity drift. Complements `diff_check.py` (behavioral) and pytest (per-symbol) with a third independent angle. Phase 0b passes: 68 functions, 9 classes, 8 constants — all match.
- **Human test checklist** at `tests/checklists/v0.3.7-pre__Phase0b__cclogger-modularization.md`: 6 high-value smoke tests + 9 detailed sections covering plugin install/cache, live tool events (Edit/Write/Grep rich format preservation), conversation events with cursor edge cases, session resume + compaction markers, `/rename` reconciliation, dazzle_filekit auto-install fallback, subtype routing, and Windows-specific UTF-8 stdin + symlink fallback. Cross-shell commands (cmd.exe, PowerShell, POSIX) for every shell-specific step.

### Changed (Phase 0b)
- **`hooks/scripts/log-command.py` reduced from 3199 → 243 LOC** (#37): now contains only the bootstrap (`sys.path.insert`), `main()` (hook event dispatch + state management), and the `cclogger.*` imports `main()` needs. All implementation logic moved into the `cclogger/` package via the move-code methodology (copy verbatim, then mechanical removal — never rewrite from memory). Behavior preserved: 101 tests pass, `diff_check.py` reports byte-identical output against a v0.3.6 baseline.
- **`tests/one-offs/test_*.py` (6 files)** (#37): import switched from `importlib.import_module("log-command")` to `importlib.import_module("cclogger")` (the re-export shim). Monkeypatches switched to the home-module string form (e.g., `"cclogger.conversation._convo_cursor_path"`, `"cclogger.debug.UNKNOWN_TOOL_WARN_DIR"`) so they intercept the lookup inside the home module rather than only the re-exported namespace alias. `sys.path` setup moved to `conftest.py`.

### Added (Phase 0a — snapshot baseline + cclogger/ skeleton)
- **`tests/snapshots/` differential test infrastructure** (#37): `synthetic_events.py` defines a 25-event fixture covering all hook event types (SessionStart, PostToolUse, UserPromptSubmit, Stop, SubagentStop, plus context compaction) and major tool categories (bash, system, io, task, todo, meta, search, ui, skill, mcp, unknown). `diff_check.py` runs the synthetic session via subprocess with redirected `HOME`/`USERPROFILE`/`USERNAME`, normalizes timestamps, and compares output to a locally-captured baseline byte-for-byte. Used to verify behavioral equivalence across each v0.3.7 phase. Baselines are gitignored — captured per-developer via `--capture-baseline` because `Path.resolve()` normalizes paths per-OS.
- **`hooks/scripts/cclogger/` empty package skeleton** (#37): placeholder for Phase 0b's subtractive modularization. Contains only `__init__.py` with a docstring noting Phase 0a status.

### Changed (Phase 0a)
- **`hooks/scripts/log-command.py`**: 5-line bootstrap added at the top (`sys.path.insert(0, ...)`) so `from cclogger.X import Y` will resolve once Phase 0b moves code into the package. Safe no-op while the package is empty. No behavioral change — `diff_check.py` reports byte-identical output, all 101 tests pass.

### Notes
- Phase 0a + 0b together complete the structural prerequisite for v0.3.7's Channel Options Framework (#38, Phase 1+). The framework — per-channel verbosity hierarchy, NewlinePolicy, formatter dispatch, hardcoded-site removal — would be unmaintainable in the 3199-line monolith but is a clean per-module refactor in the new layout.
- See `private/claude/2026-05-06__20-59-57__claude-plan__v037-modularization-and-channel-options-framework.md` for the full v0.3.7 implementation plan including Phase 0a/0b execution detail (dependency arrows, module table, test adapter strategy).

## [0.3.6] - 2026-05-05

**Channel architecture evolution epic complete** (#27, sub-issues #29-#36). Bundles seven coordinated changes that complete the channel taxonomy: bash audit, per-channel config layout, subtype routing framework, auto-generated reference docs, conversation channels (user/AI/agent), and example presets. Closes the original #1 user-configurable channels feature.

### Added
- **`convo` channel** (`.convo_*.log`): Captures user prompts (via `UserPromptSubmit` hook), AI text responses (via `Stop` + transcript read), and agent dialogue (via `SubagentStop` + transcript read). Routed via three new `message_user` / `message_ai` / `message_agent` categories.
- **`UserPromptSubmit`, `Stop`, `SubagentStop` hook events** registered in `hooks.json`. Conversation event handler in `log-command.py` extracts user prompts directly from event payload, and reads recent assistant messages from the transcript JSONL using a per-session cursor (`~/.claude/session-states/<id>.convo-cursor`).
- **Subtype routing framework** (#31): Per-category opt-in for splitting log entries into per-subtype channels (e.g., `.bash-powershell_*.log`, `.mcp-github_*.log`, `.convo-help_*.log` for the `help` subagent). Default OFF for all categories. Configure via `routing.subtype_routing.<category>: true | false | [list]`. Built-in extractors for `bash`, `mcp`, `meta`, `skill`.
- **Per-channel config directory layout** (#30): `~/.claude/plugins/settings/session-logger/` with `_global.json`, `channels/<name>.json`, and `overrides.json`. Loader auto-detects; falls back to single-file `session-logger.json` if directory absent. Both layouts produce identical in-memory `Config` objects.
- **Auto-generated channel reference docs** (#32): `scripts-repo/local/generate_channel_docs.py` produces `docs/channels.md` from `TOOL_CATEGORIES` + default routes. Includes per-category tool listings and subtype extractor descriptions.
- **Configuration guide** (#36): `docs/configuration.md` — channel/category/route mental model, common customizations, preset overview.
- **Four example config presets** (#36, in `examples/`):
  - `session-logger-minimal.json` — only `.shell_*` (copy-pasteable history)
  - `session-logger-power-user.json` — all channels + all subtype splits
  - `session-logger-agent-debug.json` — focused agent-dialogue debugging
  - `session-logger-conversation-replay.json` — only `.convo_*` for transcript replay
- **47 new pytest tests** across three new test files:
  - `tests/one-offs/test_per_channel_config.py` (10) — directory layout + content + robustness
  - `tests/one-offs/test_subtype_routing.py` (17) — extractors + expansion + path derivation
  - `tests/one-offs/test_conversation_channels.py` (20) — channel/category defaults + transcript reading + cursor persistence
- **`tools` channel** (#28, was previously v0.3.0 in this batch): AI-activity-without-prose investigation view. Routes from `_default` and `task` categories. The user's primary "find exact tool calls" channel.

### Changed
- **`Grep`, `LS`, `Glob` move from `system` to `bash`** (#29): These are conceptually shell-equivalent operations (`grep -r`, `ls`, `find . -name`). Criterion is workflow context — investigators see navigation + search + execution together in `.shell_*.log`. `Read` stays in `system` (structured file read, not a shell op). `TOOL_CATEGORIES` includes a detailed audit comment documenting the rationale.
- **Default category routes**: `_default` is now `["shell", "sesslog", "tools"]`; `task` is `["shell", "sesslog", "tools", "tasks"]`; `unknown` stays `["sesslog", "unknowns"]` (deliberately not routed to shell or tools); new `message_user` / `message_ai` / `message_agent` route to `["sesslog", "convo"]`.
- **`log_entry()` signature**: now accepts `raw_json` (used for subtype extraction).
- **Two pre-existing v0.2.1 tests updated** to assert the expanded default channel set.

### Backwards Compatibility
- **No regressions for users with customized configs**: ConfigLoader's per-key merge (verified in v0.2.1) means customized configs lacking new channels/routes auto-pick them up from defaults on next session.
- **Subtype routing is opt-in**: Default OFF for all categories. No new files appear unless the user explicitly enables.
- **Conversation capture is opt-in disable, not opt-in enable**: enabled by default. Privacy concerns: set `routing.channels.convo.enabled: false` to stop capturing user/AI prose.
- **Per-channel config layout is opt-in adoption**: Single-file layout still fully supported.

### Notes for Implementation Verification
- The `Stop` and `SubagentStop` event handlers depend on Claude Code's hook event payloads and transcript JSONL schemas, which aren't formally pinned by Anthropic. Implementation includes graceful fallbacks for multiple shapes (`message.content` and `role/content` patterns). Live verification belongs to the human checklist.
- `UserPromptSubmit` payload field name varies by SDK; handler tries `user_prompt`, `prompt`, `user_input` in order.

### Closes / Refs
- **Closes #1** (Feature: User-configurable logging channels and file routing) — final delivery of the original flexibility intent
- **Closes #27** (epic) and sub-issues #28, #29, #30, #31, #32, #33, #34, #35, #36
- **Refs #8** (tool coverage audit — partial closure via #29 work)

### Design
See `2026-05-01__17-36-55__channel-architecture-evolution-epic.md` (epic source-of-truth design with two user addenda).

## [0.3.0] - 2026-05-05

First sub-issue of the channel-architecture-evolution epic (#27). Adds the `tools` channel — the user's primary "find exact tool calls" investigation view. This channel captures everything the OLD pre-v0.2.1 `.sesslog_*` did (shell + tools + tasks + skills) but NOT the unknowns (which have their own channel since v0.2.1) and NOT the future user/AI conversation prose (coming in v0.3.5).

### Added
- **`tools` log channel** (`.tools_*.log`): Dedicated channel for AI activity (tool calls, skill invocations, task ops, shell commands) without prose. Enabled by default. Routes from the `_default` and `task` categories. The user's primary investigation channel for "find exact tool calls" workflows.
- **15 new pytest tests** in `tests/one-offs/test_tools_channel.py` covering channel creation, routing, customized-config merge behavior, and routing resolution.
- **Human test checklist** at `tests/checklists/v0.3.0__Feature__tools-channel.md`.

### Changed
- **Default category routes**: `_default` is now `["shell", "sesslog", "tools"]` (was `["shell", "sesslog"]`); `task` is now `["shell", "sesslog", "tools", "tasks"]` (was `["shell", "sesslog", "tasks"]`). The `unknown` category route is unchanged (`["sesslog", "unknowns"]` — deliberately not in the tools channel since unknowns have their own discovery surface).
- Two pre-existing v0.2.1 tests updated to assert the new defaults.

### Backwards Compatibility
- **No regressions for users with customized `category_routes`**: The config loader's per-key merge behavior (verified in v0.2.1) means customized configs lacking the `tools` channel or updated routes automatically pick them up from defaults on next session.
- **Opt-out path**: set `"routing.channels.tools.enabled": false` in `~/.claude/plugins/settings/session-logger.json`, or override the routes to exclude `tools`.

### Closes / Refs
- Closes #28 (sub-issue 1 of epic #27)
- Refs #1 (continues user-configurable channels feature; final closure in #36 / v0.3.6)

### Design
See `2026-05-01__17-36-55__channel-architecture-evolution-epic.md` for the v0.3.x epic source-of-truth design.

## [0.2.1] - 2026-05-01

Tool coverage robustness release: handles the "Anthropic adds a new tool, our log goes empty" class of bug going forward, with channel-aware routing so uncategorized tools no longer pollute purpose-specific channels (`.shell_*.log` stays clean).

### Fixed
- **PowerShell tool logged with empty content**: Same root cause as Skill (#22) — `get_command_content()` had no specific handler for `PowerShell` and the generic fallback didn't check the `command` field. Affected sesslog entries appeared as `{PowerShell:  }` with no command text. Existing transcript JSONLs are unaffected and contain the original commands; only the distilled sesslog views were degraded.
- **Empty-content warning throttling was a no-op**: The previous `_empty_content_warned: set[str]` lived in module scope, but each `PostToolUse` event spawns a fresh hook subprocess — the set never persisted, meaning every unknown tool would (re-)log on every call if/when warning was added. Replaced with a sentinel-file approach (`~/.claude/logs/.unknown_tool_warnings/<tool_name>.warned`) that throttles across all hook invocations.

### Added
- **`PowerShell` handler**: Categorized as `bash` (shares the `command` input field). Routes to the `shell` channel like Bash.
- **`unknowns` log channel** (`.unknowns_*.log`): Dedicated channel for tools without specific handlers. Enabled by default in fresh installs. Deliberately NOT in the `_default` route — keeps `.shell_*.log` free of non-shell entries.
- **`unknown` category** (renamed from `"other"`): Returned by `categorize_tool()` for any tool not in `TOOL_CATEGORIES` and not matching the `mcp__` prefix. Default route: `["sesslog", "unknowns"]`.
- **`?` marker prefix** for unknown-tool entries (`{?ToolName: content }`): Grep-friendly identification within any channel — useful for users who don't tail the dedicated `.unknowns_*.log`.
- **Throttled discovery warning** in `~/.claude/logs/hook-debug.log`: First time an unknown tool is encountered (across all sessions and processes, throttled via sentinel files), log the tool name and its input field names so a proper handler can be added. Reset by deleting `~/.claude/logs/.unknown_tool_warnings/`.

### Changed
- **Generic content-extraction fallback** now checks `command, skill, subject` in addition to the original `pattern, url, prompt, query, content`. New tools matching common shell-like, skill-like, or task-like shapes will produce useful log entries without code changes.

### Backwards Compatibility
- **No regressions for users with customized `category_routes`**: The config loader already merges per-key (defaults factory creates the base dict; user values overlay individual keys). Customized configs that lack `unknowns` channel or `unknown` route automatically pick them up from defaults on next session — no manual migration needed.
- **Opt-out path** if the dedicated channel is unwanted: set `"routing.channels.unknowns.enabled": false` in `~/.claude/plugins/settings/session-logger.json`, or override the route: `"routing.category_routes.unknown": ["sesslog"]`.

### Known Follow-ups
- MCP routing review (separate issue): MCP tools currently route to `["shell", "sesslog"]`; some belong in shell, most don't. Needs per-server analysis.
- `/sessioninfo` enhancement (separate issue): Surface a count and list of unknown tools encountered in the current session.
- Tool-coverage audit script (separate issue): Periodic scan of recent sesslogs for `{?` markers to surface persistent unknowns.

### Design
See `2026-05-01__12-03-14__tool-coverage-and-channel-routing-for-unknowns.md` for the architectural analysis.

## [0.2.0] - 2026-04-20

Dev-tooling release: replaces hand-maintained `scripts-repo/` with a git subtree from
[DazzleTools/git-repokit-common](https://github.com/DazzleTools/git-repokit-common),
generalizes upstream `sync-versions.py` to handle plugin-specific JSON version files
(via a strictly-additive `extra-targets` config), and establishes a `scripts-repo/local/`
convention for project-local tooling that lives alongside the subtree.

No runtime behavior changes for users -- this release is entirely about how the
project is developed and versioned. Closes #20 and its sub-issues #24, #25, #26.

### Changed
- **`scripts-repo/` is now a git subtree from DazzleTools/git-repokit-common** (#24, parent #20): Was a hand-maintained directory of dev scripts (sync-versions.py, update-version.sh, install-hooks.sh, hooks/, paths.sh) that had drifted from the upstream tooling shared across DazzleTools/DazzleML projects. Now pulled via `git subtree add --prefix=scripts-repo --squash` from `https://github.com/DazzleTools/git-repokit-common`. Future updates: `git subtree pull --prefix=scripts-repo repokit-common main --squash` (the `repokit-common` remote was added for convenience). The previously-stale local copies of `pre-push` (which contained a wrong-project `folder_datetime_fix/` artifact), `install-hooks.sh` (which hardcoded a project name), and other dev scripts are now replaced by their upstream versions.
- **Pre-commit hooks reinstalled from upstream**: The previously-installed pre-commit hook called the legacy `update-version.sh --auto`, which looked for `_version.py` (upstream's default) and produced a "Version update failed but continuing" warning on every commit because this project uses `version.py` (no underscore). Reinstalling via `bash scripts-repo/install-hooks.sh` swapped in the upstream pre-commit which calls `sync-versions.py --auto` -- already pyproject-aware via our `[tool.repokit-common] version-source` setting. Warning eliminated; no commit-time behavior changes otherwise.
- **`scripts-repo/.gitignore` `local/` rule removed**: Upstream's gitignore was excluding `local/` directories, which would block any consuming project from using the `scripts-repo/local/` convention this release establishes. The rule was removed (a small but real upstream improvement; will be part of the eventual upstream PR).

### Added
- **`pyproject.toml`** (#25, parent #20): Configures upstream `git-repokit-common` tooling. Sets `version-source = "version.py"` (we use a root-level version file rather than the default `<package>/_version.py`), `tag-format = "human"` to match existing CHANGELOG headers, and declares `[[tool.repokit-common.extra-targets]]` entries for our plugin JSON files.
- **`scripts-repo/local/` directory for project-local tooling** (#24, parent #20): Designated subdirectory inside the git-repokit-common subtree where project-specific or not-yet-upstreamed tools live. Avoids the structural noise of a sibling `scripts-local/` directory and gives every consuming project a clear convention for "where do my project's local scripts go." Contents:
  - `scripts-repo/local/audit_codebase.py` -- generic git-commit function-diff tool (project-agnostic; future upstream candidate)
  - `scripts-repo/local/dev-refresh.py` -- clears Claude Code plugin cache during development (replaces the old project-local `--dev-refresh` flag)
  - `scripts-repo/local/diff-harness.py` -- differential test harness (see below)
  - `scripts-repo/local/hooks/pre-commit-basic` -- minimal version-only pre-commit fallback (project-agnostic)
- **`[[tool.repokit-common.extra-targets]]` support in `scripts-repo/sync-versions.py`** (#25, parent #20): Strictly additive extension lets a project declare additional version-bearing files via pyproject.toml. Each entry: `{ path, type, field, match }`; `type` currently supports `"json"`. With no `extra-targets` config, behavior is byte-identical to upstream-pristine -- 100% backward compatible for the >10 known consumers of git-repokit-common. Also adds `check_extra_target()` for the `--check` path. Will be proposed upstream after this release ships and stabilizes. For us: `python scripts-repo/sync-versions.py --bump patch` now updates `version.py` + `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` in one command, no wrapper.
- **`scripts-repo/local/dev-refresh.py`** (#25, parent #20): Project-local script that clears the Claude Code plugin cache for this plugin (`~/.claude/plugins/cache/dazzle-claude-plugins/session-logger/<version>/`) so reinstalls during development don't serve stale cached files. Ported from the old `scripts-repo_bak/sync-versions.py`'s `--dev-refresh` flag. Stays project-local because the cache path is Claude-Code-plugin-specific. CLI: `python scripts-repo/local/dev-refresh.py [versions...] [--dry-run] [--force]`.
- **`scripts-repo/local/diff-harness.py`** (#25, parent #20): Differential test harness that clones the project into `%TEMP%` via `git clone --no-local` (NOT git worktrees -- worktrees share `.git/`, leaking commits/hooks), checks out the `pre-subtree-migration-v0.1.11` tag in one copy and `HEAD` in the other, runs identical version operations in both, and diffs the SemVer outputs. Verification methodology for the `extra-targets` work: the harness FAILed until extra-targets was implemented (proving the gap), then PARTIAL-passed (proving SemVer equivalence; only stylistic `PHASE = None` vs `PHASE = ""` upstream-convention diff remains). Includes mandatory cleanup, a leakage check that confirms `~/.claude/plugins/cache/` and the original repo's git log are unchanged, and a `--use-worktree` flag for validating uncommitted changes during iteration.
- **Test checklist** (`tests/checklists/v0.2.0__Epic__scripts-repo-subtree-and-extra-targets.md`): Hand-runnable verification covering the entire #20/#24/#25/#26 work surface. Six-test High-Value Verification block plus eight detailed sections (pyproject.toml + restructure, extra-targets feature, dev-refresh.py, end-to-end version bump, backward compat for upstream consumers, subtree pull merge behavior, pre-commit regressions, differential equivalence). All testable sections verified PASS via the `tester` agent.

### Removed
- **`scripts-repo/` hand-maintained tooling** (#24, parent #20): The entire prior `scripts-repo/` directory was deleted before re-adding as a subtree. Two project-local files (`audit_codebase.py`, `hooks/pre-commit-basic`) were preserved in `scripts-repo/local/`. Backup tag `pre-subtree-migration-v0.1.11` retains the pre-migration state for rollback if needed.

## [0.1.11] - 2026-04-19

### Fixed
- **Skill tool logged with empty content** (#22): `get_command_content()` had no specific handler for the `Skill` tool, causing all Skill invocations to log as `{Skill:  }` (empty). The generic fallback only checked fields `pattern, url, prompt, query, content` -- none of which match the Skill tool's actual `skill` and `args` fields.

### Added
- **`Skill` tool handler**: Logs skill name plus a configurable preview of args
  - Format with args: `{Skill: <skill-name> <- "args preview..." }`
  - Format without args: `{Skill: <skill-name> }`
- **`skill_args_length` config option** (`performance.skill_args_length`): Max characters for the Skill args preview. Default `100`, `0` disables args entirely (name only). Schema updated.

## [0.1.10] - 2026-04-06

### Fixed
- **Session directory name truncation**: `sanitize_dirname()` had a hardcoded 50-character limit that silently truncated long session names in directory names (e.g., `...-pt2` became `...-pt`). Now dynamically computes budget from the 255-char filesystem limit minus the `__{guid}_{username}` suffix overhead, with a floor of 20 characters.
- **Session rename corrupts non-log filenames** (#17): `_rename_files_for_session_change()` used blind `str.replace()` which corrupted files like `transcript.jsonl` when the old session name was a common substring (e.g., `c` in `transcript`). Now:
  - Only renames log files (`.sesslog_*`, `.shell_*`, `.tasks_*`) -- skips `transcript.jsonl` and other non-log files
  - Uses structural regex (`(?<=__){name}(?=__{guid})`) to target the session name field instead of arbitrary substrings

## [0.1.9] - 2026-04-06

### Fixed
- **Escalating pip install for PEP 668** (#18): `_ensure_dazzle_filekit()` now tries three strategies:
  1. Normal `pip install` (Windows, venvs, Ubuntu 22.04)
  2. `pip install --user` (restricted global installs)
  3. `pip install --break-system-packages` (Ubuntu 24.04+ with PEP 668)
- **install.py now installs dazzle-filekit** (#18): Changed from "Optionally install" to actually installing with the same escalating strategy

### Changed
- Added `run-hook.mjs` to `install.py` file list for manual installations

## [0.1.8] - 2026-04-06

### Changed
- **Cross-platform Node.js hook launcher** (#19): Replace direct `python` call with `node run-hook.mjs`
  - `run-hook.mjs` finds Python 3 on any platform (`python3` on Unix, `python` on Windows)
  - Eliminates backslash path issues on Linux
  - Non-blocking: exits 0 with stderr message if Python not found
  - Warns when `CLAUDE_PLUGIN_ROOT` env var is missing (npm-installed Claude Code)
  - 60s timeout on Python subprocess
  - Claude Code guarantees Node.js availability (it's a Node.js app)
- Updated installation docs with official Anthropic links and npm migration guidance
- Updated README with native installer requirement note

## [0.1.7] - 2026-04-06

### Added
- **Auto-install dazzle-filekit** (#18): Automatically installs `dazzle-filekit>=0.2.1` if missing
  - Sentinel file prevents repeated pip attempts if install fails
  - Retries after 1 hour in case failure was transient
- **Task description length config**: New `task_description_length` performance setting
  - `0` = no truncation (default), any positive integer = max characters
  - JSON Schema and example config updated
- **Resilient error handling**: Top-level exception handler wraps `main()`
  - Logs fatal errors to `hook-debug.log` instead of crashing
  - Outputs `{"continue": true}` so Claude Code is never blocked by hook failure

### Fixed
- **Task file proliferation** (#15): Unified `get_task_filename_context()` to delegate to `get_filename_context()`
  - Eliminates divergent `__` (double underscore) separator before username
  - Task logs now use same filename pattern as sesslog and shell channels
  - Stops the rename-create-sequence cycle that produced 100+ files per session

### Changed
- `get_task_content()` now accepts optional `Config` parameter for configurable truncation
- Removed hardcoded 100-character truncation from TaskCreate descriptions

## [0.1.6] - 2026-02-12

### Added
- **Configuration system** (#1): User-configurable logging with JSON Schema validation
  - Config location: `~/.claude/plugins/settings/session-logger.json`
  - Performance settings: `max_file_size_for_line_search`, `content_preview_length`
  - Display settings: `verbosity`, `datetime`, `pwd`
  - Routing configuration: channels, category routes, tool overrides
  - JSON Schema at `hooks/schemas/session-logger.schema.json` for IDE autocompletion
  - Zero-config backwards compatible (all defaults match previous behavior)
- **Read line range logging**: Read tool now shows offset/limit as clickable line references
  - Format: `{Read: "path:100-149" }` for offset=100, limit=50
  - Format: `{Read: "path:100" }` for offset only
  - Format: `{Read: "path" (50L) }` for limit only (first N lines)
- **Edit line number logging**: Edit tool now shows line number where change was made
  - Format: `{Edit: "path:42" ← "content..." (1L) }`
  - Uses `find_line_number()` to locate the edited line in the file
  - Skips line detection for files >2MB for performance
- **ToolSearch support** (#11): Added logging for MCP tool discovery
  - Supports `tool_search_tool_regex` and `tool_search_tool_bm25`
  - Format: `{tool_search_tool_regex: <query> }`
  - Triggers automatically when MCP tools would consume >10% of context

### Changed
- Increased file size limit for line detection from 1MB to 2MB

## [0.1.4] - 2026-02-01

### Added
- **Grep glob filter logging** (#6): Grep entries now show file glob filter alongside pattern
  - Format: `{Grep: pattern | "*.tsx" }` when glob filter is used
- **Write/Edit content preview** (#7): Shows first 20 characters of content being written
  - Format: `{Write: "path" ← "content preview..." }`
  - Newlines escaped as `\n`, non-printable chars replaced with `?`
- **Agent context identification** (#5): Framework for identifying subagent tool calls
  - When detected, format: `{Bash|Explore: command }` or `{Read|Plan: "path" }`
  - Debug logging to investigate available JSON fields for agent detection
- **Version sync tool** (`scripts-repo/sync-versions.py`): Centralized version management
  - `--bump patch/minor/major` to increment version
  - `--demote patch/minor/major` to decrement version
  - `--set X.Y.Z` to set version directly
  - `--phase alpha/beta/rc1/none` to set release phase
  - `--check` to verify all files are in sync
  - `--dev-refresh [VERSION...]` to clear plugin cache for development testing
    - Without args: clears target version
    - With args: clears specified version(s) (e.g., `--dev-refresh 0.1.3 0.1.4 0.1.5`)
    - Use `--dry-run` to preview, `--force` to skip confirmations
  - Calls `update-version.sh` automatically
- **Developer guide** (`docs/dev.md`): Documentation for contributors

### Fixed
- **Session resume detection** (#9): SESSION START marker now written when resuming a session
  - Previously, resumed sessions didn't get new markers due to persistent `.started` flag
  - Now clears `.started` and `.run` flags on SessionStart hook
  - Run number correctly increments by recounting markers in log file

### Changed
- Content extraction for Read, Write, Edit, MultiEdit now handled separately
- Added `truncate_preview()` helper for safe content truncation
- Added `format_tool_name()` helper for agent-prefixed tool names

## [0.1.3] - 2026-02-01

### Fixed
- **Plugin architecture fixes**: Plugin now loads correctly via marketplace installation
- Fixed `.claude-plugin/plugin.json`: Removed invalid `claude-code` key, added `./` prefix to paths
- Fixed `hooks/hooks.json`: Added required outer `hooks` wrapper, changed `{plugin_dir}` to `${CLAUDE_PLUGIN_ROOT}`
- Fixed `.claude-plugin/marketplace.json`: Changed from listing metadata schema to marketplace hosting schema

### Changed
- Marketplace installation now uses self-hosted marketplace approach
- Installation commands: `claude plugin marketplace add "DazzleML/claude-session-logger"` then `claude plugin install session-logger@dazzle-claude-plugins`
- Updated installation documentation with working methods

### Removed
- Removed redundant root `marketplace.json` (now only `.claude-plugin/marketplace.json`)

## [0.1.2] - 2026-01-29

### Added
- Plugin marketplace installation: `claude plugin install session-logger`
- Detailed installation guide at `docs/installation.md`
- GitHub release badge in README

### Changed
- Restructured README: Quick Start and Usage sections now appear before Project Structure
- Streamlined README by moving detailed installation to separate docs file

### Fixed
- Log entry formatting: added space before closing `}` for better copy-paste
- File paths now wrapped in double-quotes for VS Code path clicking
- PWD path in log entries now quoted for consistency

## [0.1.1] - 2026-01-29

### Fixed
- CI workflow paths updated for new plugin structure (`hooks/scripts/`)
- Various plugin restructuring fixes

## [0.1.0] - 2026-01-29

### Added
- Initial release
- `log-command.py` - Main session logging hook
  - Session-specific log files in `~/.claude/sesslogs/`
  - Task operation logging (TaskCreate, TaskUpdate, TaskList, TaskGet)
  - Run number tracking across session resumes
  - Overflow file handling for large logs
- `rename_session.py` - Session renaming helper
- Auto-naming from working directory on SessionStart
  - Generic folder detection (code, project, local, src, etc.)
  - Drive letter inclusion for context (e.g., `c--code`)
  - Path-based naming with parent context (e.g., `my-project--local`)
- Transcript symlink creation (`transcript.jsonl` in sesslog directory)
- `/renameAI` command - AI-assisted session naming
- `/sessioninfo` command - Session state inspection
- `install.py` - Installation script for hooks and commands
- `settings.json.example` - Hook configuration template

### Dependencies
- Requires `dazzle-filekit>=0.2.1` for cross-platform path handling
