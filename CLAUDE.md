# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Project**: claude-session-logger
**Description**: Real-time session logging, command history, and auto-naming for Claude Code
**Language**: Python
**Created**: 2026-01-29

## Architecture

This project provides Claude Code hooks that log session activity in real-time to `~/.claude/sesslogs/`.

### Key Components

```
claude/
├── hooks/
│   ├── log-command.py       # Main hook - session logging, auto-naming, transcript symlinks
│   └── rename_session.py    # Helper for AI-assisted session renaming
├── commands/
│   ├── renameAI.md          # /renameAI slash command
│   └── sessioninfo.md       # /sessioninfo slash command
└── settings.json.example    # Hook configuration template
```

### How It Works

1. **SessionStart hook** triggers on new session:
   - Creates sesslog directory at `~/.claude/sesslogs/{name}__{id}_{user}/`
   - Auto-names session from working directory if unnamed
   - Creates transcript symlink for easy discovery

2. **PostToolUse hook** triggers after each tool call:
   - Logs tool name, timestamp, parameters to `.sesslog_*.log`
   - Logs task operations to `.tasks_*.log`
   - Tracks run numbers across session resumes

### Directory Layout (User's ~/.claude/)

```
~/.claude/
├── hooks/                    # Installed hooks (from this project)
├── commands/                 # Installed commands (from this project)
├── settings.json             # Hook configuration
├── sesslogs/                 # Session log output
│   └── {session-name}__{session-id}_{user}/
│       ├── .sesslog_*.log    # Tool call logs
│       ├── .shell_*.log      # Shell command output
│       ├── .tasks_*.log      # Task operations
│       └── transcript.jsonl  # Symlink to transcript
└── session-states/           # Session state persistence
    ├── {id}.json             # Full state
    ├── {id}.name-cache       # Cached name
    └── {id}.run              # Run number
```

## Common Development Commands

```bash
# Verify Python syntax
python -m py_compile claude/hooks/log-command.py

# Lint
flake8 claude/hooks/*.py --max-line-length=127

# Test installation
python install.py --check
```

## Plugin Development Workflow

### Local Marketplace Setup

This project uses a **local marketplace** for development. The marketplace is configured to pull from the local `github/` folder, NOT from GitHub.

**Check current marketplace configuration:**
```bash
cat ~/.claude/plugins/known_marketplaces.json
```

Expected output for local development:
```json
{
  "dazzle-claude-plugins": {
    "source": {
      "source": "directory",
      "path": "C:\\code\\claude-projects\\claude-session-logger\\github"
    }
  }
}
```

**IMPORTANT**: Periodically verify the marketplace is still pointing to your local folder. It may be changed to test different configurations (e.g., pulling from GitHub instead).

### Development Workflow

1. **Edit** files in `github/` folder (the source of truth)
2. **Verify syntax**: `python -m py_compile hooks/scripts/log-command.py`
3. **Reinstall** from local marketplace:
   ```bash
   claude plugin install session-logger@dazzle-claude-plugins
   ```
4. **Test** in a new Claude Code session
5. **Check debug log**: `~/.claude/logs/hook-debug.log`

### Setting Up Local Marketplace (if needed)

If the marketplace isn't configured for local development:
```bash
cd C:\code\claude-projects\claude-session-logger\github
claude plugin marketplace add "./"
```

### Testing Changes

After reinstalling the plugin:
1. Start a new Claude Code session (or use a tool in existing session)
2. Check `~/.claude/logs/hook-debug.log` for debug output
3. Verify sesslogs are created correctly in `~/.claude/sesslogs/`

### Manual Copy Fallback

If the marketplace reinstall isn't working or for quick one-off testing:
1. Copy modified hook directly to the cache:
   ```bash
   cp hooks/scripts/log-command.py ~/.claude/plugins/cache/dazzle-claude-plugins/session-logger/0.1.5/hooks/scripts/
   ```
2. Start a new Claude Code session
3. Check `~/.claude/logs/hook-debug.log` for debug output
4. Verify sesslogs are created correctly

## Key Functions in log-command.py

| Function | Purpose |
|----------|---------|
| `derive_session_name_from_cwd()` | Auto-generate session name from path |
| `get_session_name()` | Retrieve session name from multiple sources |
| `ensure_transcript_symlink()` | Create transcript.jsonl symlink |
| `log_tool_call()` | Log tool usage to sesslog |
| `log_task_operation()` | Log task operations separately |

## Dependencies

- **dazzle-filekit** (required) - Cross-platform path normalization and symlink creation

## Private Branch Guidelines

### Documentation Requirements

- **ALWAYS** document all work performed in timestamped files under `./private/claude/`
- Use filename format: `YYYY_MM_DD__HH_MM_SS__(TOPIC).md`
- Include all commands executed, their outputs, and summaries

### Version Control Practices

- The `private` branch is LOCAL ONLY - never push to remote repositories
- Commit frequently to track all changes and edits
- Merge to `dev` excluding `private/`, `CLAUDE.md`, and local config

### Private Content Structure

```
private/
├── claude/         # All Claude-assisted work documentation
│   ├── instructions/   # Core workflow instructions
│   └── YYYY_MM_DD__HH_MM_SS__(TOPIC).md
├── convos/         # Conversation logs (protected from commits)
└── logs/           # System logs (protected from commits)
```

## The Dev Workflow Process

When tackling complex problems or making significant decisions, use **THE PROCESS** - a 5-stage systematic approach:

### 🔁 The 5 Stages:

1. **Problem Analysis** - Define and understand the full context
2. **Conceptual Exploration** - Explore the nature and relationships
3. **Brainstorming Solutions** - Generate and evaluate multiple approaches
4. **Synthesis and Recommendation** - Combine best elements into optimal solution
5. **Implementation Plan** - Create actionable roadmap

**When to use**: For any complex problem, design decision, bug investigation, or strategic choice.

## Project-Specific Notes

### Cross-Platform Considerations

- Paths are normalized via `dazzle_filekit.normalize_cross_platform_path()`
- Handles Git Bash (`/c/...`), WSL (`/mnt/c/...`), and native Windows paths
- Symlink creation has Windows fallbacks (os.symlink → dazzlelink → mklink)

### Generic Folder Detection

The auto-naming logic considers these folders "generic" and includes parent context:
- home, user, users, code, projects, project, work, dev, src, local, current, etc.

Example: `C:\code` → `c--code`, `C:\code\my-project\local` → `my-project--local`

### Session State Files

Session state is persisted to survive Claude Code restarts:
- `.json` - Full state including conversation context
- `.name-cache` - Quick name lookup
- `.run` - Current run number
- `.started` - Session start marker
