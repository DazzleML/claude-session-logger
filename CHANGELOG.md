# Changelog

All notable changes to claude-session-logger will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
