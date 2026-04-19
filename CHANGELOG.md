# Changelog

All notable changes to claude-session-logger will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
