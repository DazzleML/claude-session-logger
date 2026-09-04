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
- **Subagent Capture** - Each subagent's own tool calls, narration, thinking and final report land in its own file, bracketed by start and stop lines
- **Thinking** - Claude's reasoning is recorded alongside what it said, as `{THINK: ...}` and `{AGENT-THINK:<type> ...}`; switchable per channel or off entirely
- **Two Timelines** - `.sesslog_*` is everything; `.sesslog-main_*` is the same session with the agents' internal work left out
- **Failed Calls Marked** - A tool call that fails is logged like any other, with its reason inline: `{Edit: path [FAILED: anchor not found] }`
- **AI Rename** - `/renameAI` command for AI-assisted session naming
- **Session Info** - `/sessioninfo` command to inspect current session state

## Quick Start

```bash
claude plugin marketplace add "DazzleML/claude-session-logger"
claude plugin install session-logger@dazzle-claude-plugins
```

Requires the [native Claude Code installer](https://docs.anthropic.com/en/docs/claude-code/getting-started) (not npm). For other install methods (local clone, manual) and for troubleshooting see the [Installation Guide](docs/installation.md).

### Updating

```bash
claude plugin marketplace update dazzle-claude-plugins
claude plugin update session-logger@dazzle-claude-plugins
```

(Note: `claude plugin install` does **not** update an existing install.)  For additional details on verifying versions, multi-user machines, etc. see the [Updating](docs/installation.md#updating) section of the Installation Guide.

## Usage

### Automatic Session Logging

Once installed, all Claude Code sessions are automatically logged to:

```
~/.claude/sesslogs/{session-name}__{session-id}_{user}/
├── .sesslog_*.log          # Everything, one timeline (tool calls, prose, thinking, agents)
├── .sesslog-main_*.log     # The same session without the agents' internal work
├── .shell_*.log            # Shell command output
├── .tools_*.log            # Tool calls without prose
├── .tasks_*.log            # Task operations log
├── .convo_*.log            # User prompts, AI responses, agent dialogue
├── .agents_*.log           # Subagent activity
├── .agents-<type>_*.log    # One file per agent type: its dispatch, work, thinking and report
├── .unknowns_*.log         # Tools the plugin doesn't recognize yet
└── transcript.jsonl        # Symlink to transcript file
```

Every channel is configurable and a few more ship switched off — see the [Configuration Guide](docs/configuration.md).

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

## Tips

- **First-time `/rename`**: The built-in `/rename` command may fail on first use in a new session (before any tools run). Just run it again or use any tool first. See [Known Quirks](docs/installation.md#known-quirks).

## Configuration

The hook creates these directories automatically:

- `~/.claude/sesslogs/` - Session log files
- `~/.claude/session-states/` - Session state persistence
- `~/.claude/logs/` - Debug logs (when enabled)

Which activity lands in which file is configurable per channel: turn channels on or off, split them per subagent, choose how much of each entry to show, drop entries you don't want, and label concurrent agents by id. See the [Configuration Guide](docs/configuration.md) and [Log Channels](docs/log-channels.md); `examples/` has five drop-in presets.

### Debug Logging

To enable debug logging, the hook writes to `~/.claude/logs/hook-debug.log`. Check this file if hooks aren't working as expected. Invocations slower than a second also record one line each in `~/.claude/logs/session-logger-perf.log`.

## Platform Support

| Platform | Status |
|----------|--------|
| Windows 10/11 | Tested |
| Windows (MINGW64/Git Bash) | Tested |
| WSL / WSL2 | Tested |
| Linux | Tested (Ubuntu 6.8.x) |
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
│       ├── run-hook.mjs          # Cross-platform Node.js launcher
│       └── rename_session.py
├── commands/                 # Plugin commands
│   ├── renameAI.md
│   └── sessioninfo.md
├── scripts-repo/             # Dev tooling (name avoids the plugin system's scripts/ handling)
│   ├── repokit-common/       # Git subtree from DazzleTools/git-repokit-common
│   │   ├── hooks/            # Git hooks (pre-commit, etc.)
│   │   ├── install-hooks.sh
│   │   ├── sync-versions.py  # Version sync (configured via pyproject.toml)
│   │   └── ...               # issue/backlink/sesslog tooling
│   ├── generate_channel_docs.py  # Project-local tooling at scripts-repo root
│   ├── dev-refresh.py / diff-harness.py / audit_codebase.py
│   └── pre-commit-basic     # manual fallback hook variant
│       ├── audit_codebase.py    # git-commit function-diff tool
│       ├── dev-refresh.py       # Clear plugin cache during development
│       ├── diff-harness.py      # Differential test harness for sync-versions
│       └── hooks/pre-commit-basic
├── pyproject.toml            # Configures sync-versions.py extra-targets, etc.
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

These tools are complementary. You might use cchistory for quick historical lookups and claude-session-logger for real-time monitoring and session organization.

## Contributing

Contributions welcome! Please open an issue or submit a pull request.

See **[Developer Guide](docs/dev.md)** for:
- Local plugin testing workflow
- Version management with `sync-versions.py`
- Debugging tips and session state files
- Pull request checklist

Like the project?

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/djdarcy)

## Related Projects

- [Claude-Session-Backup](https://github.com/DazzleML/Claude-Session-Backup) - Companion tool: git-backed backup of the sessions this plugin logs, with timeline view, deletion detection, and session restore
- [dazzle-filekit](https://github.com/DazzleLib/dazzle-filekit) - Cross-platform file operations toolkit
- [cchistory](https://github.com/eckardt/cchistory) - Extract shell commands from Claude Code transcripts
- [Claude Code](https://claude.ai/code) - Anthropic's CLI for Claude

## License

claude-session-logger, copyright (C) 2026 Dustin Darcy

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.