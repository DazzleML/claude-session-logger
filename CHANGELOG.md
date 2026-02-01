# Changelog

All notable changes to claude-session-logger will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
