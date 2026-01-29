# claude-session-logger

[![GitHub release](https://img.shields.io/github/v/release/DazzleML/claude-session-logger?include_prereleases&color=brightgreen)](https://github.com/DazzleML/claude-session-logger/releases)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#platform-support)

> **Session logging, command history, and auto-naming for Claude Code**

A hook-based extension for Claude Code that provides persistent session logging, automatic session naming from your working directory, and transcript discovery via symlinks.

## Features

- **Session Logging** - Log all tool calls to session-specific files in `~/.claude/sesslogs/`
- **Auto-Naming** - Sessions automatically named from working directory (e.g., `c--code` or `my-project`)
- **Transcript Symlinks** - Easy access to transcript files via `transcript.jsonl` in sesslog directories
- **Run Tracking** - Track multiple runs within a session with run markers
- **Task Logging** - Dedicated logging for TaskCreate/TaskUpdate/TaskList operations
- **AI Rename** - `/renameAI` command for AI-assisted session naming
- **Session Info** - `/sessioninfo` command to inspect current session state

## Quick Start

### Option 1: Plugin Marketplace (Easiest)

```bash
claude plugin install session-logger
```

### Option 2: Local Plugin Directory

```bash
# Clone the repository
git clone https://github.com/DazzleML/claude-session-logger.git

# Install Python dependencies
pip install -r requirements.txt

# Run Claude Code with the plugin
claude --plugin-dir /path/to/claude-session-logger
```

For manual installation or troubleshooting, see the [Installation Guide](docs/installation.md).

## Usage

### Automatic Session Logging

Once installed, all Claude Code sessions are automatically logged to:

```
~/.claude/sesslogs/{session-name}__{session-id}_{user}/
├── .sesslog_*.log          # Session log (tool calls, timestamps)
├── .shell_*.log            # Shell command output
├── .tasks_*.log            # Task operations log
└── transcript.jsonl        # Symlink to transcript file
```

### Auto-Naming Examples

Sessions are automatically named based on your working directory:

| Working Directory | Auto-Generated Name |
|-------------------|---------------------|
| `C:\code\my-project` | `my-project` |
| `C:\code` | `c--code` |
| `C:\code\project\local` | `project--local` |
| `/home/dev/app` | `app` |

Generic folder names (code, project, local, src, etc.) trigger path-based naming with parent context.

### Commands

#### `/renameAI`
AI-assisted session renaming. Analyzes your conversation and suggests a descriptive name.

```
> /renameAI
Analyzing conversation...
Suggested name: "AuthRefactorAndTests"
```

#### `/sessioninfo`
Display current session state including ID, name, run number, and log paths.

```
> /sessioninfo
Session ID: 833a100e-d959-47aa-9db2-d22fdb6d7659
Session Name: my-project
Run Number: 2
Sesslog Directory: ~/.claude/sesslogs/my-project__833a100e-..._User/
```

## Configuration

The hook creates these directories automatically:

- `~/.claude/sesslogs/` - Session log files
- `~/.claude/session-states/` - Session state persistence
- `~/.claude/logs/` - Debug logs (when enabled)

### Debug Logging

To enable debug logging, the hook writes to `~/.claude/logs/hook-debug.log`. Check this file if hooks aren't working as expected.

## Platform Support

| Platform | Status |
|----------|--------|
| Windows 10/11 | Tested |
| Windows (MINGW64/Git Bash) | Tested |
| WSL / WSL2 | Tested |
| Linux | Expected to work |
| macOS | Expected to work |

## Project Structure

This project follows the Claude Code plugin architecture:

```
claude-session-logger/
├── .claude-plugin/           # Plugin metadata
│   ├── plugin.json
│   └── marketplace.json
├── hooks/                    # Plugin hooks (for Claude Code)
│   ├── hooks.json
│   └── scripts/
│       ├── log-command.py
│       └── rename_session.py
├── commands/                 # Plugin commands
│   ├── renameAI.md
│   └── sessioninfo.md
├── scripts-repo/             # Development/repo scripts (not part of plugin)
│   ├── hooks/                # Git hooks (pre-commit, etc.)
│   ├── install-hooks.sh
│   └── update-version.sh
├── version.py
└── ...
```

## How It Works

1. **SessionStart Hook** - On session start:
   - Creates sesslog directory
   - Auto-names session from working directory (if unnamed)
   - Creates transcript symlink
   - Initializes run tracking

2. **PostToolUse Hook** - After each tool call:
   - Logs tool name, timestamp, and context to sesslog
   - Tracks task operations separately
   - Updates session state

3. **Session State** - Persisted in `~/.claude/session-states/`:
   - `{session-id}.json` - Full session state
   - `{session-id}.name-cache` - Cached session name
   - `{session-id}.run` - Current run number
   - `{session-id}.started` - Session start flag

## Comparison with cchistory

[cchistory](https://github.com/eckardt/cchistory) is a great tool that extracts shell commands from Claude Code's transcript files after the fact.

**claude-session-logger** takes a different approach:

| Feature | claude-session-logger | cchistory |
|---------|----------------------|-----------|
| Approach | Real-time hooks (watch live) | Post-hoc parsing |
| Data source | Separate log channels | Claude's transcript files |
| Shell commands | Yes | Yes |
| Task operations | Yes (TaskCreate, etc.) | No |
| File read/writes | Yes | No |
| Session naming | Yes (auto + AI) | No |
| Run tracking | Yes | No |
| Transcript symlinks | Yes | No |

**When to use which:**
- **cchistory**: Quick extraction of shell commands from past sessions
- **claude-session-logger**: Real-time structured session management — watch commands as they happen, copy-paste on the fly, spot-check Claude's actions live

These tools are complementary — you might use cchistory for quick historical lookups and claude-session-logger for real-time monitoring and session organization.

## Contributing

Contributions welcome! Please open an issue or submit a pull request.

Like the project?

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/djdarcy)

## Related Projects

- [cchistory](https://github.com/eckardt/cchistory) - Extract shell commands from Claude Code transcripts
- [dazzle-filekit](https://github.com/DazzleLib/dazzle-filekit) - Cross-platform file operations toolkit
- [Claude Code](https://claude.ai/code) - Anthropic's CLI for Claude

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.