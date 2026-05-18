# Changelog

All notable changes to claude-session-logger will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — v0.3.7 work in progress

### Added (tasks channel coverage extension, #87)
- **`todo` category now routes to the `tasks` channel** by default (`["shell", "sesslog", "tools", "tasks"]`). TodoWrite was previously category `todo` with no entry in `_default_category_routes`, falling through to `_default` (no tasks channel). Now TodoWrite lands alongside the Task* family in `.tasks_*.log`. `action_only.todo: True` is unchanged -- TodoWrite still logs in action-only mode by default; this just adds the tasks channel to its routing destination.
- **New `routing.mcp_server_routes` primitive**: additive channel-routing keyed by MCP server name (the `<server>` segment in `mcp__<server>__<tool>`). When a tool from a given server runs, the server's channels are unioned into the route from `category_routes`. Default `{"todoai": ["tasks"]}` -- Todoist tools (`mcp__todoai__*`) land in the tasks channel without enumerating every individual tool name. Users can add new server mappings or override existing ones via `~/.claude/plugins/settings/session-logger.json`. `tool_overrides` (highest precedence; replaces everything) skips `mcp_server_routes` consultation -- being specific wins over additive layering.
- **`get_task_content` TodoWrite branch**: when a TodoWrite event lands in the tasks channel, the formatter now produces `TODOS: N item(s) [Np/Nip/Nc] first: <first content>` rather than the bare `{TodoWrite }` fallback. Includes status-count breakdown (pending / in_progress / completed) and a truncated first-item preview. `task_description_length` caps the preview length when configured.
- **`log-command.py` always stuffs `raw_json` into `LogEntry.metadata`** (was previously only for `task` category) so the `task-only` formatter's `get_task_content` fallback path can extract task-shaped content from any tool routed to the tasks channel (e.g., Todoist MCP via `mcp_server_routes`). `task_content` precompute extended to the `todo` category too.
- **TaskOutput / TaskStop handlers now extract `tool_response`** (was task_id only). TaskOutput pulls `tool_response.task.output` (the actual stdout from the backgrounded process) and emits a `summary_template` with a `{snippet}` placeholder -- so DefaultFormatter applies per-channel `max_chars` truncation. TaskStop pulls `tool_response.message` for the outcome string (e.g., `"Task 42 stopped successfully"`). Previously both rendered as just `{TaskOutput: 42}` / `{TaskStop: 42}` with no signal in any channel.
- **TaskOutput re-routed to `[sesslog, tools, tools-output]`** (dropped from shell). Per the `.bash_history` mental model, `TaskOutput` isn't a runnable shell command. Routed to: `tools` (100-char snippet for AI-activity investigation), `sesslog` (200-char preview, new per-role cap), `tools-output` (full content; channel disabled by default). TaskStop stays at `[shell, sesslog, tools]` (kill commands fit `.bash_history`; output is small).
- **New `.tools-output_*` channel** (disabled by default, opt-in like `.fileio_*`). Captures full process outputs from `TaskOutput` (and any other future verbose-content tools) with `verbosity="full"` and `NewlinePolicy.RENDER` for multi-line readability. Users enable via `routing.channels.tools-output.enabled = true` when investigating long-running processes. Template pattern for any future "verbose-content" channels.
- **New per-role sesslog cap**: `routing.channels.sesslog.options.verbosity` gains `"task-output": {"max_chars": 200}`. Long process stdout no longer balloons the kitchen-sink channel; users investigating full output enable `.tools-output_*` or read `transcript.jsonl` directly. Mirrors the existing per-role caps for `write`/`edit`/`multi-edit`/`notebook-edit` (capped at 20 chars each).
- **New default `tool_overrides`** for `TaskStop` and `TaskOutput` re-route them away from the `tasks` channel. Verified against `c:\code-ext\claude-code\tools\TaskStopTool\` and `TaskOutputTool\`: both are process management for background bash/agent subprocesses (kill a running process, read its stdout), NOT task-list operations. They share the `Task` prefix only by name. Default override drops the tasks channel while keeping shell/sesslog/tools. Users can restore the tasks channel via their own `tool_overrides` if desired.
- **Schema**: `routing.mcp_server_routes` added with `oneOf` semantics (additive routing per MCP server). `routing.category_routes` default updated to include `todo`. `routing.tool_overrides` default updated to include `TaskStop`/`TaskOutput` re-routing entries (was `{}`).
- **27 new pytest tests** in `tests/one-offs/test_tasks_channel_coverage.py` across 5 sections: `todo` category routing (4 tests), `mcp_server_routes` default (2), additive semantics including `tool_overrides`-replace precedence + no-duplication + non-MCP isolation (5), user-override via `apply_override_routing_config` (4), TodoWrite formatter rendering including malformed-input resilience and Task* regression (6), TaskStop/TaskOutput default routing including end-to-end + user-override (6). Plus 1 updated test in `test_config_merge_protocol.py` reflecting the new `tool_overrides` defaults (was pinning empty dict).
- **Snapshot baseline re-captured.** Single intentional delta: `.tasks_*.log` synthetic-test entry adds a new `[[TIMESTAMP]] {TODOS: 2 item(s) [1p/1ip/0c] first: Build snapshot infrastructure }` line ahead of the existing `CREATE: Verify snapshot diff` line. Old baseline preserved at `tests/snapshots/v036_baseline_pre_87_tasks_coverage/`.

### Notes (#87 follow-ups)
- **GitHub #50 filed** for convo-channel per-line agent identity (`{AGENT:<TYPE>:` instead of bare `{AGENT:`) -- requires subagent_type extraction from the transcript JSONL, which is unimplemented today. Separate effort.
- **Newer Claude Code tools** (TeamCreate, TeamDelete, BriefTool, ScheduleCronTool, RemoteTriggerTool, SendMessageTool) absent from `TOOL_CATEGORIES` are NOT in this commit's scope -- they belong with Github #44 sub-issue 6 (event-surface canvass).
- **GH issue creation via `gh` Bash command** intentionally NOT in scope -- would require content-pattern sniffing on Bash command strings, which breaks the data-driven routing model.

### Changed (Channels-as-Data hardening — dead-equivalent branches removed)
- **`SessionContext.get_task_filename_context()` removed** (was an alias to `get_filename_context()` since the v0.2.x #15 fix unified task naming with all other channels). All three call sites in `cclogger/logger.py` now use `get_filename_context()` directly.
- **`SessionLogger._get_file_path()` collapsed** from a 3-way `if file_type == "shell" / "sesslog" / "tasks"` chain to a generic `_target_paths`-or-`_get_channel_path` lookup. Any declared channel resolves the same way — file_prefix carries channel identity, the filename-context method is universal.
- **`SessionLogger._get_channel_path()` lost its `("shell", "sesslog", "tasks")` fallback** (which would only fire if the user had nuked those channels from `routing.channels`, in which case raising `Unknown channel` is the honest outcome). Also lost its two `== "tasks"` branches that picked `get_task_filename_context()` over `get_filename_context()` (now identical).
- **`SessionLogger._get_channels_for_tool()` no longer masks a missing `_default` route** with the hardcoded `["shell", "sesslog"]` backstop. If the user explicitly removes `_default` from their `category_routes`, we route to `[]` rather than silently honoring the wrong thing.
- **`reconcile_session_files(channel_names=)` is now required** (was `Optional[list[str]] = None` with a `["sesslog", "shell", "tasks"]` fallback for the legacy enumeration). The only caller (`SessionLogger._reconcile_files`) has always passed the config-derived channel list since the #49 fix; the fallback was a backward-compat backstop with no live caller.
- **Test removed**: `test_default_channel_names_preserves_legacy_behavior` in `test_rename_reconciliation.py` pinned the removed fallback.
- Net: -40 LOC across 4 files (`logger.py`, `models.py`, `reconciliation.py`, `test_rename_reconciliation.py`). Snapshot byte-identical (15 log files). 331 tests pass (one removed). Pure dead-code removal; no behavioral change.

### Changed (BREAKING: per-channel subtype split opt-in; supersedes #48, Closes #49)
- **CRITICAL: `routing.subtype_routing.<category>` config key REMOVED**: the v0.3.3 category-wide subtype-routing toggle is gone. It fired subtype-derived files (`.sesslog-bash`, `.tools-grep`, etc.) for every channel the category routed to, with no way to scope per-channel. Replaced by `routing.channels.<name>.options.subtype_split: bool | list[str]` (default `false` on every channel except `agents`).
- **`ChannelOptions.subtype_split` field**: per-channel opt-in. `True` = split for any subtype the channel's traffic generates (e.g., `.shell-bash_*`, `.shell-grep_*` for the `shell` channel); `list[str]` (e.g., `["help", "senior-engineer"]`) = split only when the extracted subtype matches; `False` (default) = no split. Single-level only — `.agents-help_*` never chains to `.agents-help-bash_*`.
- **`agents` channel ships with `subtype_split=True`** as the lone default-true channel: `.agents-help_*`, `.agents-senior-engineer_*`, `.agents-explore_*`, etc. materialize automatically when agents fire. Users no longer need to set `routing.subtype_routing.meta: true` (which would also have over-fired on any other channel `meta` routed to). The `examples/session-logger-agent-debug.json` preset is simplified — the `subtype_routing` block is dropped because the new default takes care of it.
- **Migration**: any `routing.subtype_routing` key in user config is silently ignored at merge time (no field exists on the `RoutingConfig` dataclass for it to land on; JSON parses fine, merge skips it). Users who relied on the old `subtype_routing.meta: true` get equivalent behavior automatically from the new `agents` default. Users who relied on `subtype_routing.bash: true` to split `.shell_*` should add `routing.channels.shell.options.subtype_split: true` to their config.
- **No backwards-compatibility shim per project policy** ("we have very few users; breaking changes are OK if the design is right"). CHANGELOG documents the schema break; debug-log emits no special warning.

### Fixed (rename reconciliation enumerates all channels + subtype derivatives, Closes #49)
- **Bug B: `reconcile_session_files` orphaned every non-legacy channel on session rename**: the v0.3.6 enumeration hardcoded `["sesslog", "shell", "tasks"]`. When a session was renamed, `tools`, `convo`, `unknowns`, `agents`, `fileio`, AND all subtype-derived files (`.shell-bash_*`, `.agents-help_*`, etc.) were NOT renamed — they kept getting re-created under the OLD session name on every subsequent hook event. Result: duplicate-per-channel-pair pollution in any session that had been renamed AND had subtype splits enabled. Surfaced live in 2026-05-16 in the cross-project sesslog directory `CLAUDE-SESSION-BACKUP__2026-5-16__making-sure-we-can-detect-deleted-sessions-and-recov__...`.
- **Fix**: `reconcile_session_files` now accepts a `channel_names: list[str]` parameter (passed as `list(config.routing.channels.keys())` from `SessionLogger._reconcile_files`) and additionally scans the directory for any `.<base>-<subtype>_*` derivatives via the new `discover_channel_basenames()` helper. Subtype derivatives are reconciled in-place (renamed on disk) but not added to the returned target-paths dict — they materialize lazily on the next subtype-split write.
- **`_rename_files_for_session_change` rewritten** to drop the `log_prefixes = (".sesslog_", ".shell_", ".tasks_")` filter. Now walks every file whose name embeds the session GUID and starts with `.`, renaming any structural match. Non-log files (transcript.jsonl, `.overflow_migrated_v0.3.7`, `.orphan_session_name_swept_v0.3.7`) are skipped because they don't match the pattern.

### Added (one-time orphan-session-name sweep, Closes #49)
- **`sweep_orphan_session_name_files(session_dir, current_session_name, session_id)`** in `cclogger/file_io.py`: called from `SessionLogger.__init__` after `migrate_overflow_files`, gated by `is_new_session_run()`. Scans the session directory for any file whose embedded session name doesn't match the current name, moves it to `<session_dir>/baks/<filename>` (numeric suffix on collision). Idempotent via the `.session-logger-orphans-swept` sentinel marker (mirrors the `migrate_overflow_files` pattern from #47). Recoverable cleanup — never deletes.
- **`_embedded_session_name(filename, session_id)`** helper extracts the embedded session name from a structural log filename (handles both base channels and subtype-derived siblings; strips `--NNN` sequence numbers).

### Changed (housekeeping marker rename + self-documentation)
- **Sentinel filenames renamed** for self-explanation:
  - `.overflow_migrated_v0.3.7` → `.session-logger-overflow-migrated`
  - `.orphan_session_name_swept_v0.3.7` → `.session-logger-orphans-swept`
- **Sentinel content is now self-documenting** — each file explains in-place what it marks, why it exists, and confirms it's safe to delete (deletion just re-runs the corresponding no-op scan on next SessionStart).
- **`README.session-logger.md` dropped per session dir** alongside any sentinel — one-time descriptive README explaining the channel-file naming conventions, what the `.session-logger-*` markers are for, and what `baks/` is. Name avoids collision with user-placed `README.md` files; never overwrites an existing file at that path. Not written at the `sesslogs/` root.
- **Legacy sentinel names still recognized**: existing dirs with the old `.overflow_migrated_v0.3.7` / `.orphan_session_name_swept_v0.3.7` sentinels short-circuit the migration AND drop the new-named sentinel alongside, so future checks find the new name immediately. No re-migration of already-cleaned dirs.

### Added (one-shot bulk cleanup script, scripts-repo/local/)
- **`scripts-repo/local/cleanup_subtype_orphans_v0.3.7.py`**: utility for the v0.3.7-pre upgrade. Walks `~/.claude/sesslogs/` and moves stale `.<channel>-<subtype>_*.log` files (left over from when `routing.subtype_routing.bash: true` over-fired) into `~/.claude/sesslogs/bak/<session-dir-name>/`. `.agents-*` is preserved (intentional default subtype split). With `--include-legacy-overflows`, also cleans up legacy `.overflow.N` files in dormant session dirs (whose `SessionLogger` never reopened to absorb them). Dry-run by default; use `--apply` to perform moves.

### Notes
- **Tests: 328** (294 prior + 18 #47 + 16 new for subtype_split + rename + sweep). Total breakdown roughly: 101 Phase 0 + 45 Phase 1 + 56 Phase 2+3 + 8 Phase 4 + 19 Phase 5 + 44 Phase 6 #45 + 18 #47 + 16 new (test_subtype_routing.py rewritten + test_rename_reconciliation.py new + assertions updated in test_marker_broadcast.py + test_config_merge_protocol.py + test_agents_channel.py end-to-end).
- **Snapshot baseline re-captured.** Single intentional delta from v0.3.7-pre prior: `.agents-Explore_bash.exe__synthetic-test-project__...` now materializes because `agents` defaults `subtype_split=True`. Old baseline preserved at `tests/snapshots/v036_baseline_pre_subtype_split_default/`.
- **Architectural foundation**: `ChannelOptions` is now the single home for per-channel knobs (verbosity, formatter, newline_policy, role_labels, suppress_markers, subtype_split). No more category-keyed routing config influencing per-channel behavior — the channel decides.

### Fixed (append+lock write primitive, Closes #47)
- **CRITICAL: replace temp-file+rename with append+lock primitive** (#47): `cclogger/file_io.atomic_append()` previously wrote via `tempfile.mkstemp` + `shutil.move`, which requires DELETE access on the destination. On Windows this fails whenever any external reader holds a handle on the channel file — antivirus scanners (millisecond holds), Explorer thumbnailers (seconds), and user-held editor handles (minutes to hours). Failed writes fell back to `.overflow.N` files that accumulated without reconciliation (5 events across 4 sessions in the bug-reporter's debug log).
- **Fix architecture**: new `cclogger/file_lock.py` module exposes `lock_exclusive()` / `lock_nonblocking()` / `unlock()` with `msvcrt.locking()` on Windows and `fcntl.flock()` on POSIX. `atomic_append` now opens with `open(path, 'ab')` (cooperative sharing modes on both platforms via Python's `_SH_DENYNO` default), acquires an exclusive byte-0 lock, writes + fsyncs, then releases. Cooperative sharing modes mean external read handles do NOT block writes — the editor-while-hook-writes failure mode is solved structurally rather than papered over with retry. POSIX `O_APPEND` is atomic for writes < `PIPE_BUF` (~4KB); Windows behaves equivalently under the lock.
- **Path 1 retry as defense-in-depth**: 3 attempts with exponential backoff (10ms/50ms/200ms) on lock acquisition failure before falling through to the overflow-file fallback. With append+lock as primary, this path is essentially unreachable under normal use.
- **One-time overflow migration**: `migrate_overflow_files(session_dir)` absorbs any legacy `.overflow.N` files from prior versions into the corresponding main log files on first SessionStart after upgrade. Sorted by mtime to preserve write order, grouped by base file name, single `═══ MIGRATED FROM OVERFLOW: N file(s) absorbed at <ts> ═══` banner per merge event. Idempotent via `.overflow_migrated_v0.3.7` sentinel marker in the session directory — runs at most once per session dir, gated additionally by `is_new_session_run()` so it doesn't even scan on subsequent events of the same run.
- **18 new pytest tests** in `tests/one-offs/test_file_io_overflow.py` (#47) across 4 sections: AppendLockBasic (write semantics, gap markers, null-byte stripping, Unicode round-trip, auto-parent-dir), RetryAndOverflow (retry succeeds on second attempt, all-retries fail writes to overflow, overflow picks next N when first full), Migration (no overflows → sentinel only, missing dir handled, single overflow absorbed with banner, multiple overflows in mtime order, multi-base grouping, sentinel prevents re-run, single banner per base regardless of count), EditorHeldFile (append succeeds while external reader holds handle; Windows share-modes allow concurrent append).
- **Snapshot baseline byte-identical**: write-path swap with no formatting change. `python tests/snapshots/diff_check.py` confirms 14 log files match baseline byte-for-byte. Total tests: 294 (276 prior + 18 #47).

### Fixed (Phase 6 — config merge protocol, Closes #45)
- **CRITICAL: per-key merge of channel configuration** (#45): `ConfigLoader._apply_new_config()` previously did whole-record replacement of `ChannelConfig` instances whenever a user touched any field of an existing channel. This had two manifestations both downstream of the same architectural mistake:
  1. **Original**: any channel override missing `file_prefix` was silently skipped entirely (the `if "file_prefix" in channel_data` gate). Users couldn't simply set `{"convo": {"enabled": false}}` — they had to redundantly redeclare `file_prefix` for the override to register.
  2. **Extended scope discovered during Phase 5 live verification**: user enables `fileio` with the `file_prefix` workaround → the loader builds a fresh `ChannelConfig` with `ChannelOptions()` defaults — silently REPLACING the shipped `verbosity="full"` + `newline_policy=RENDER` defaults that make `.fileio_*` actually capture full file content. Users got 20-char path-only previews instead of the intended diff-readable content.
- **Fix architecture**: introduced an `apply_override(target, override_dict) → None` classmethod on every typed config dataclass (`Config`, `RoutingConfig`, `ChannelConfig`, `ChannelOptions`, `PerformanceConfig`). Each method walks fields explicitly present in the override, mutates only those fields on the existing instance, recurses into nested dataclasses by calling their `apply_override`, and owns its own coercion (string→enum for `NewlinePolicy`, dict validation for `verbosity`, etc.). `_apply_new_config` collapses to `Config.apply_override(config, data)`. Existing channels get per-field merge; new channels still require `file_prefix` (the sentinel that distinguishes "declare new" from "override existing"). The protocol is the foundation for the v0.4.x #44 Channels-as-Data epic — adding a new nested typed config structure now means adding one `apply_override` method, not patching loader code in another place.
- **38 new pytest tests** in `tests/one-offs/test_config_merge_protocol.py` (#45) across 6 sections: `ChannelOptions` per-field merge contract (11 tests including reserved-keyword validation, explicit-null reset, non-dict input handling), `ChannelConfig` recursion into options, `RoutingConfig` existing-vs-new channel dispatch (9 tests including the bug regression — partial overrides preserve shipped options), `PerformanceConfig` clamping preserved, `Config` top-level dispatch + idempotency + combined overrides, end-to-end `ConfigLoader` integration (5 tests covering both bug manifestations via single-file and per-channel-directory layouts).
- **Schema update**: `hooks/schemas/session-logger.schema.json` makes `file_prefix` optional in channel entries with documentation explaining the new-vs-existing semantics.
- **One updated test**: `test_options_absent_yields_default_options` in `test_channel_options.py` was pinning the old buggy behavior (expected partial override of an existing channel to wipe options to defaults). Renamed to `test_options_absent_in_partial_override_preserves_shipped_options` and updated to assert the corrected behavior.

### Notes (Phase 6)
- **Snapshot baseline byte-identical**: the fix only affects user-config overrides; default behavior with no user config is unchanged. `python tests/snapshots/diff_check.py` confirms 14 log files match baseline byte-for-byte.
- **Total tests: 276** (101 Phase 0 + 45 Phase 1 + 56 Phase 2+3 + 8 Phase 4 + 19 Phase 5 incl. #46 regressions + 44 Phase 6 #45 protocol + 3 mid-phase carryover).
- **Architectural foundation for v0.4.x epic #44**: the apply_override protocol replaces ad-hoc construction logic with a uniform per-field-merge contract every typed config structure will follow. Adding new nested dataclasses (e.g., per-channel rotation policies, custom formatter parameters, channel-level filter rules) costs one method on the dataclass instead of patching the loader.

### Changed (Phase 6 follow-up — apply_override module extraction)
- **`cclogger/config_merge.py`** — new module owning the merge protocol entirely. The 5 `apply_override` classmethods previously attached to `Config`/`RoutingConfig`/`ChannelConfig`/`ChannelOptions`/`PerformanceConfig` are now free functions (`apply_override_config`, `apply_override_routing_config`, etc.) in this module. The two coercion helpers `parse_bool` and `_validate_per_role_dict` also moved here since they exist solely to support the merge protocol. Net effect: data definitions in `models.py` are now pure (no methods); the merge implementation is isolated to one file so future swaps (e.g., to OmegaConf or another library, per the help-agent prior-art survey) touch a single module without affecting the dataclass layout. Behavior unchanged — 276 tests pass + snapshot byte-identical.

### Added (Phase 5 — `.agents_*` channel, Closes #40)
- **New `.agents_*` channel** for sub-agent invocations (#40): dedicated log surface where `Task` tool entries land. "Show me everything I asked the senior-engineer to do this week" becomes a single `tail .agents_*.log`, not a grep across sesslog. Channel enabled by default; users can disable via `routing.channels.agents.enabled = false`.
- **`meta` category route updated to `["sesslog", "agents"]`** (#40): Task invocations no longer route to `.shell_*` (agent calls aren't shell commands) or `.tools_*` (agents has its own dedicated view). sesslog (kitchen sink) still captures them. Users with customized `routing.category_routes.meta` are unaffected — the per-key merge preserves overrides.
- **Subtype routing for agents** (#40): enable `routing.subtype_routing.meta = true` to split per-agent files via the existing `_subtype_for_meta` extractor (reads `subagent_type` from raw JSON). Produces `.agents-senior-engineer_*`, `.agents-help_*`, `.agents-explore_*`, etc. Subtype-derived channels inherit parent `agents` ChannelOptions by default (declare-to-override / omit-to-inherit contract from Phase 2+3 applies).
- **17 new pytest tests** in `tests/one-offs/test_agents_channel.py` (#40) across 6 sections testing the four-layer user model (channel + categories+verbosity + subtypes + cross-channel — layer 4 is the sibling epic #43): channel exists in defaults, route inclusion/exclusion (sesslog/agents in, shell/tools out), Task tool categorization unchanged, per-channel options resolution, subtype extraction, subtype channel options inheritance, Phase 4 marker broadcast covers agents channel.

### Changed (Phase 5)
- **Tests `test_existing_channels_still_present` and `test_all_default_channels_present`** (in `test_unknown_tool_routing.py` and `test_tools_channel.py`) updated to expect 8 channels in `_default_channels()` (was 7) — adds `agents`. Both tests pin the channel set as a regression check; they're updated alongside Phase 5.

### Fixed (Phase 5)
- **CRITICAL: hook now reads user config** (#46): `hooks/scripts/log-command.py` was calling the legacy `load_configuration()` directly instead of `ConfigLoader.load()`. The legacy function only reads `~/.claude/claude-history.json` (display-only settings: verbosity, datetime, pwd) and never touches the new-style `~/.claude/plugins/settings/session-logger.json`. **Every user-config-driven feature added since v0.3.6 has been silently dead in the live hook.** Affects: `routing.subtype_routing`, `routing.channels.*.options.suppress_markers`, `routing.channels.*.enabled`, `routing.channels.*.options.{verbosity,formatter,newline_policy,role_labels}`, `routing.category_routes` overrides, `routing.tool_overrides`, and any user-defined channels. Discovered during Phase 5 live verification when `subtype_routing.meta = true` failed to produce `.agents-<subagent_type>_*` files; debug instrumentation in `_expand_with_subtype_channels` showed `subtype_routing={}` in the hook subprocess despite `ConfigLoader.load()` returning `{'meta': True}` from the same Python interpreter when invoked directly. Fix is one line: change `load_configuration(context_string)` to `ConfigLoader.load(context_string)`. Two new AST-based regression tests in `test_agents_channel.py` pin the call site so this can't silently regress. Bug existed since v0.3.6 (verified at `0.3.6/hooks/scripts/log-command.py:3092`); Phase 0b modularization preserved it because the goal was byte-identical behavior.
- **`Agent` tool now routes to `meta` category** (#40): Claude Code's live agent-spawning tool is `Agent` (per source clone canvass 2026-05-12). Without this fix the `.agents_*` channel would not fire on real production agent calls — they would fall through to `unknown` and land in `.unknowns_*.log` with the `??:` prefix (verified empirically before the fix when this session's own `Agent` invocation landed as `{?Agent: ...}` in `.unknowns_*`). The `_subtype_for_meta` extractor reads `tool_input.subagent_type` so subtype routing works for the live tool.
- **Removed `"Task": "meta"`** from `TOOL_CATEGORIES` (#40): the bare `Task` key was distinct from the agent-spawning tool and conflated with the `Task*` family (`TaskCreate`/`TaskUpdate`/`TaskList`/`TaskGet`/`TaskOutput`/`TaskStop`), which are TodoAI task-management tools correctly categorized as `task`. Bare `Task` now falls through to `unknown` if it ever appears, where it's visibly logged in `.unknowns_*` for diagnosis rather than silently masquerading as an agent invocation.
- **Snapshot fixture updated**: `tests/snapshots/synthetic_events.py` renamed its synthetic agent invocation from `Task` to `Agent` to match the live tool name; baseline re-captured. Pre-rename baseline preserved at `tests/snapshots/v036_baseline_pre_phase5_agent_fix/`.

These regressions were surfaced by the v0.4.x epic #44 sub-issue #6 research (canvass of Claude Code's event surface) delivered in `notes/research/2026-05-12__claude-code-event-surface.md`. The research also flags ~15 additional tool names present in Claude Code source but missing from `TOOL_CATEGORIES` (mostly feature-flagged team/worktree/cron tools); those are deferred to the v0.4.x epic since they don't affect Phase 5's correctness.

### Notes (Phase 5)
- **Snapshot baseline re-captured.** The Phase 5 deltas: `.shell_*` and `.tools_*` lose the Task entry (correct — meta no longer routes there), `.agents_*` is created with the Task entry plus the Phase 4 broadcast markers, `.sesslog_*` retains the Task entry (kitchen sink unchanged). The subagent session directory also gains a `.agents_*` file with its session-start broadcast marker. Old baseline preserved at `tests/snapshots/v036_baseline_pre_phase5/` for historical reference.
- **Total tests: 227** (101 Phase 0 + 45 Phase 1 + 56 Phase 2+3 + 8 Phase 4 + 17 Phase 5).
- **Layers 1-3 of the v0.4.x "Channels as Data" epic empirically validated by Phase 5.** Agents is the natural test surface — channel exists in defaults (layer 1), category route brings Task entries via the existing meta route (layer 2), subtype routing splits per-agent (layer 3). Layer 4 (cross-channel navigation back to source) remains scoped to Github #43.

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
- **Design decisions** are pinned in `2026-05-09__23-01-19__channel-options-framework-pin-design-decisions.md` — captures the user's verbatim responses to ten open design points and synthesizes them into binding decisions.

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
- See `2026-05-06__20-59-57__claude-plan__v037-modularization-and-channel-options-framework.md` for the full v0.3.7 implementation plan including Phase 0a/0b execution detail (dependency arrows, module table, test adapter strategy).

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
