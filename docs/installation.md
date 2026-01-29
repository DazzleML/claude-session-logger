# Installation Guide

This guide covers all installation methods for claude-session-logger.

## Prerequisites

- **Python 3.9+** - Required for hook scripts
- **Claude Code** - The Anthropic CLI tool
- **dazzle-filekit** - Required Python package for cross-platform path handling

---

## Installation Methods

### Method 1: Plugin Marketplace (Easiest)

> **Status**: Plugin architecture not yet validated. See Method 3 for tested approach.

Install directly from the Claude Code plugin marketplace:

```bash
claude plugin install session-logger
```

To verify installation:

```bash
claude plugin list
```

To update to the latest version:

```bash
claude plugin update session-logger
```

**Note**: Marketplace installation automatically handles dependencies.

---

### Method 2: Plugin Directory (For Development)

> **Status**: Plugin architecture not yet validated. See Method 3 for tested approach.

Use Claude Code's `--plugin-dir` flag to load the plugin directly from a local directory.

```bash
# Clone the repository
git clone https://github.com/DazzleML/claude-session-logger.git
cd claude-session-logger

# Install Python dependencies
pip install -r requirements.txt

# Run Claude Code with the plugin
claude --plugin-dir /path/to/claude-session-logger
```

**For persistent use**, you can:
- Add `--plugin-dir` to a shell alias
- Configure it in Claude Code settings (if supported)

---

### Method 3: Manual Installation (Tested)

Copy plugin files directly into your Claude config directory.

#### Step 1: Copy hook scripts

```bash
# Create hooks directory
mkdir -p ~/.claude/hooks

# Copy hook files
cp hooks/scripts/log-command.py ~/.claude/hooks/
cp hooks/scripts/rename_session.py ~/.claude/hooks/
```

#### Step 2: Copy command files

```bash
# Create commands directory
mkdir -p ~/.claude/commands

# Copy command files
cp commands/renameAI.md ~/.claude/commands/
cp commands/sessioninfo.md ~/.claude/commands/
```

#### Step 3: Configure hooks in settings.json

Add the following to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "python ~/.claude/hooks/log-command.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "python ~/.claude/hooks/log-command.py"
          }
        ]
      }
    ]
  }
}
```

#### Step 4: Install dependencies

```bash
pip install dazzle-filekit
```

Or install all dependencies:

```bash
pip install -r requirements.txt
```

---

## Verifying Installation

After installation, start a new Claude Code session and check:

1. **Session logs created**: Look for files in `~/.claude/sesslogs/`
2. **Commands available**: Type `/sessioninfo` to see session state
3. **No errors**: Check `~/.claude/logs/hook-debug.log` if something seems wrong

---

## Troubleshooting

### Hooks not running

1. Check that Python is in your PATH
2. Verify the hook files are executable
3. Check `~/.claude/logs/hook-debug.log` for errors

### Missing dependencies

If you see import errors:

```bash
pip install dazzle-filekit
```

### Permission issues (Linux/macOS)

Make hook scripts executable:

```bash
chmod +x ~/.claude/hooks/*.py
```

### Windows path issues

Use forward slashes or escaped backslashes in settings.json:

```json
"command": "python C:/Users/YourName/.claude/hooks/log-command.py"
```

---

## Uninstalling

### If using --plugin-dir

Simply stop using the `--plugin-dir` flag.

### If using manual installation

```bash
# Remove hook files
rm ~/.claude/hooks/log-command.py
rm ~/.claude/hooks/rename_session.py

# Remove command files
rm ~/.claude/commands/renameAI.md
rm ~/.claude/commands/sessioninfo.md

# Remove hooks configuration from ~/.claude/settings.json
# (Edit manually to remove the hooks section)

# Optionally remove session logs
rm -rf ~/.claude/sesslogs/
rm -rf ~/.claude/session-states/
```

---

## Platform-Specific Notes

### Windows

- Tested with Git Bash (MINGW64) and WSL/WSL2
- PowerShell and cmd expected to work
- Use forward slashes in paths when possible

### macOS

- Expected to work (not yet tested)
- No special configuration anticipated

### Linux

- Expected to work (not yet tested)
- No special configuration anticipated
