# Changelog

All notable changes to claude-session-logger will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
