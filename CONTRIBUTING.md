# Contributing to claude-session-logger

Thank you for considering contributing to claude-session-logger! This project aims to make Claude Code sessions more manageable through real-time logging and session organization.

## Code of Conduct

Please be respectful and constructive in all interactions. We're all here to make Claude Code better.

## How Can I Contribute?

### Reporting Bugs

Before creating a bug report, please:
1. Check the [existing issues](https://github.com/DazzleML/claude-session-logger/issues) to avoid duplicates
2. Collect relevant information:
   - Your OS and Python version
   - Claude Code version
   - Relevant log output from `~/.claude/logs/hook-debug.log`
   - Steps to reproduce the issue

### Suggesting Enhancements

We welcome ideas for:
- New log channels or data to capture
- Improvements to auto-naming logic
- Better cross-platform support
- Integration with other tools

Open a [feature request](https://github.com/DazzleML/claude-session-logger/issues/new?template=feature-request.md) with your idea.

### Pull Requests

#### Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR-USERNAME/claude-session-logger.git
   cd claude-session-logger
   ```
3. Create a branch:
   ```bash
   git checkout -b feature/my-improvement
   ```

#### Development

The main hook code is in `claude/hooks/log-command.py`. Key areas:

| Area | Functions |
|------|-----------|
| Auto-naming | `derive_session_name_from_cwd()`, `GENERIC_FOLDER_NAMES` |
| Logging | `log_tool_call()`, `log_task_operation()` |
| Session state | `get_session_state()`, `save_session_state()` |
| Symlinks | `ensure_transcript_symlink()` |

#### Testing Your Changes

1. Copy your modified hook to `~/.claude/hooks/`:
   ```bash
   cp claude/hooks/log-command.py ~/.claude/hooks/
   ```
2. Start a new Claude Code session
3. Check debug output:
   ```bash
   tail -f ~/.claude/logs/hook-debug.log
   ```
4. Verify sesslogs are created correctly

#### Code Style

- Follow PEP 8 guidelines
- Keep line length under 127 characters
- Add docstrings to new functions
- Use type hints where practical

#### Submitting

1. Ensure your code passes lint checks:
   ```bash
   flake8 claude/hooks/*.py --max-line-length=127
   ```
2. Verify Python syntax on multiple versions:
   ```bash
   python -m py_compile claude/hooks/log-command.py
   ```
3. Update CHANGELOG.md if adding features
4. Push your branch and open a pull request

### Areas for Contribution

Looking for something to work on? Consider:

- **Windows improvements**: Better symlink handling, path edge cases
- **macOS testing**: Verify full functionality on macOS
- **Documentation**: Usage examples, troubleshooting guides
- **Performance**: Optimize for very long sessions
- **New features**: Additional log channels, filtering options

## Questions?

Open a [discussion](https://github.com/DazzleML/claude-session-logger/discussions) or reach out via issues.

Thank you for helping make Claude Code sessions easier to manage!
