# Installation Guide

This guide covers all installation methods for claude-session-logger.

## Prerequisites

- **[Claude Code](https://code.claude.com/docs/en/getting-started)** (native installer) - The npm version is [deprecated](https://code.claude.com/docs/en/getting-started#deprecated-npm-installation) and has known issues with plugin variable expansion
- **Python 3.9+** - Required for hook scripts
- **dazzle-filekit** - Required Python package for cross-platform path handling (auto-installed by the hook if missing)

```bash
# Install Claude Code (native installer)
curl -fsSL https://claude.ai/install.sh | bash    # Linux/macOS
irm https://claude.ai/install.ps1 | iex           # Windows PowerShell

# Install Python dependency (optional -- hook auto-installs if missing)
pip install dazzle-filekit
```

---

## Installation Methods

### Method 1: From GitHub (Recommended)

Install via the DazzleML marketplace:

```bash
# Add the DazzleML marketplace (one-time setup)
claude plugin marketplace add "DazzleML/claude-session-logger"

# Install the plugin
claude plugin install session-logger@dazzle-claude-plugins
```

To verify installation:

```bash
claude plugin list
```

To update to the latest version:

```bash
claude plugin update session-logger@dazzle-claude-plugins
```

---

### Method 2: From Local Clone (For Development)

Use this method when developing or testing changes to the plugin.

```bash
# Clone the repository
git clone https://github.com/DazzleML/claude-session-logger.git
cd claude-session-logger

# Install Python dependencies
pip install -r requirements.txt

# Add as local marketplace (from inside the repo directory)
claude plugin marketplace add "./"

# Install the plugin
claude plugin install session-logger@dazzle-claude-plugins
```

**Switching between local and GitHub sources:**

```bash
# Remove current marketplace
claude plugin marketplace remove dazzle-claude-plugins

# Add the other source
claude plugin marketplace add "DazzleML/claude-session-logger"  # GitHub
# OR
claude plugin marketplace add "./"  # Local (from repo directory)

# Re-install
claude plugin install session-logger@dazzle-claude-plugins
```

---

### Method 3: Plugin Directory Flag (Quick Testing)

For quick testing without permanent installation:

```bash
claude --plugin-dir /path/to/claude-session-logger
```

**Note**: This method requires the flag every session.

---

### Method 4: Manual Installation (Legacy)

Copy plugin files directly into your Claude config directory.

#### Step 1: Copy hook scripts

```bash
# Create hooks directory
mkdir -p ~/.claude/hooks

# Copy hook files
cp hooks/scripts/log-command.py ~/.claude/hooks/
cp hooks/scripts/run-hook.mjs ~/.claude/hooks/
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
            "command": "node ~/.claude/hooks/run-hook.mjs"
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
            "command": "node ~/.claude/hooks/run-hook.mjs"
          }
        ]
      }
    ]
  }
}
```

---

## Verifying Installation

After installation, start a new Claude Code session and check:

1. **Plugin status**: Run `claude plugin list` to see installed plugins
2. **Session logs created**: Look for files in `~/.claude/sesslogs/`
3. **Commands available**: Type `/sessioninfo` to see session state
4. **No errors**: Check `~/.claude/logs/hook-debug.log` if something seems wrong

---

## Troubleshooting

### Plugin not found in marketplace

If `claude plugin install` fails with "Plugin not found":

1. Ensure marketplace is added: `claude plugin marketplace list`
2. Re-add if missing: `claude plugin marketplace add "DazzleML/claude-session-logger"`
3. Try updating: `claude plugin marketplace update dazzle-claude-plugins`

### Hooks not running

1. Check that Node.js and Python 3 are in your PATH
2. On Linux/macOS, ensure `python3` is available (the hook launcher tries `python3` first)
3. Check `~/.claude/logs/hook-debug.log` for errors
4. Ensure plugin is enabled: `claude plugin list` should show `✔ enabled`

### Hooks fail with path errors (npm-installed Claude Code)

If hooks fail with errors like `/hooks/scripts/run-hook.mjs: not found` or similar path issues, you may be running the **npm-installed version** of Claude Code, which does not expand `${CLAUDE_PLUGIN_ROOT}` in plugin hook commands.

**Fix:** Switch to the native Claude Code installer:

```bash
# Linux/macOS
curl -fsSL https://claude.ai/install.sh | bash

# Then restart Claude Code
```

The native installer correctly expands plugin variables. The npm version is [deprecated by Anthropic](https://code.claude.com/docs/en/getting-started#deprecated-npm-installation) and has known plugin system issues. See the [migration guide](https://code.claude.com/docs/en/getting-started#migrate-from-npm-to-native) for switching.

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

### Marketplace already exists error

If you see "marketplace already installed":

```bash
claude plugin marketplace remove dazzle-claude-plugins
claude plugin marketplace add "DazzleML/claude-session-logger"
```

---

## Uninstalling

### If using marketplace installation

```bash
# Uninstall the plugin
claude plugin uninstall session-logger@dazzle-claude-plugins

# Optionally remove the marketplace
claude plugin marketplace remove dazzle-claude-plugins
```

### If using manual installation

```bash
# Remove hook files
rm ~/.claude/hooks/log-command.py
rm ~/.claude/hooks/run-hook.mjs
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

## Plugin Cache Location

When installed via marketplace, plugins are cached at:

```
~/.claude/plugins/cache/{marketplace-name}/{plugin-name}/{version}/
```

For this plugin:
```
~/.claude/plugins/cache/dazzle-claude-plugins/session-logger/0.1.3/
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

---

## Known Quirks

### /rename requires transcript to exist

The built-in `/rename` command may fail with `ENOENT` on first use in a brand new session (before any tool calls create the transcript file). If this happens, simply run `/rename` a second time, or use any tool first (like asking a question), then rename.

```
> /rename my-session-name
  ⎿  Error: ENOENT: no such file or directory, open '...transcript.jsonl'

> /rename my-session-name
  ⎿  Session renamed to: my-session-name
```

This is a Claude Code behavior, not specific to this plugin.
