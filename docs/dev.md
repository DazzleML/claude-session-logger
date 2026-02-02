# Developer Guide

This guide covers development workflows for contributing to claude-session-logger.

## Quick Start for Development

```bash
# Clone and enter the project
git clone https://github.com/DazzleML/claude-session-logger.git
cd claude-session-logger

# Install as local plugin for testing
claude plugin marketplace add "./"
claude plugin install session-logger@dazzle-claude-plugins

# Start a new Claude Code session to load the hooks
```

## Project Structure

```
claude-session-logger/
├── .claude-plugin/           # Plugin packaging
│   ├── plugin.json           # Plugin metadata (version here)
│   └── marketplace.json      # Marketplace config (version here too)
├── hooks/
│   ├── hooks.json            # Hook registration
│   └── scripts/
│       └── log-command.py    # Main logging logic
├── commands/                 # Slash commands (/renameAI, /sessioninfo)
├── scripts-repo/             # Development scripts
│   ├── sync-versions.py      # Version synchronization
│   └── update-version.sh     # Git version string updater
├── version.py                # Canonical version source (MAJOR.MINOR.PATCH)
└── docs/
    ├── installation.md       # User installation guide
    └── dev.md                # This file
```

## Version Management

### Version Locations

Version numbers exist in multiple files. **`version.py` is the source of truth.**

| File | Field | Example |
|------|-------|---------|
| `version.py` | `MAJOR`, `MINOR`, `PATCH` | `0`, `1`, `4` |
| `version.py` | `__version__` | `0.1.4_main_12-20260201-abc123` |
| `.claude-plugin/plugin.json` | `"version"` | `"0.1.4"` |
| `.claude-plugin/marketplace.json` | `"version"` (×2) | `"0.1.4"` |

### Sync Versions Script

The `sync-versions.py` script keeps everything in sync:

```bash
# Check if versions are synchronized
python scripts-repo/sync-versions.py --check

# Bump patch version (0.1.4 -> 0.1.5)
python scripts-repo/sync-versions.py --bump patch

# Bump minor version (0.1.4 -> 0.2.0)
python scripts-repo/sync-versions.py --bump minor

# Bump major version (0.1.4 -> 1.0.0) - requires confirmation
python scripts-repo/sync-versions.py --bump major

# Demote patch version (0.1.4 -> 0.1.3)
python scripts-repo/sync-versions.py --demote patch

# Demote minor version (0.1.4 -> 0.0.0)
python scripts-repo/sync-versions.py --demote minor

# Set version directly (e.g., 0.1.4 -> 0.2.1)
python scripts-repo/sync-versions.py --set 0.2.1

# Skip confirmation for major changes (use with caution)
python scripts-repo/sync-versions.py --bump major --force
python scripts-repo/sync-versions.py --set 2.0.0 --force

# Preview changes without modifying
python scripts-repo/sync-versions.py --bump patch --dry-run

# Sync without updating git version string
python scripts-repo/sync-versions.py --no-git-ver

# Clear plugin cache for development testing (--dev-refresh)
python scripts-repo/sync-versions.py --dev-refresh              # Clears target version
python scripts-repo/sync-versions.py --set 0.1.4 --dev-refresh  # Clears 0.1.4
python scripts-repo/sync-versions.py --dev-refresh 0.1.3 0.1.4  # Clears multiple versions

# Preview cache clearing without removing
python scripts-repo/sync-versions.py --dev-refresh --dry-run

# Skip confirmation prompts (use after reviewing with --dry-run)
python scripts-repo/sync-versions.py --dev-refresh 0.1.3 0.1.4 --force
```

### Version Bumping Workflow

```bash
# 1. Make your code changes
# 2. Update CHANGELOG.md with new version section
# 3. Bump and sync versions
python scripts-repo/sync-versions.py --bump patch

# 4. Verify everything is in sync
python scripts-repo/sync-versions.py --check

# 5. Commit all changes
git add -A
git commit -m "Release v0.1.5: description of changes"

# 6. Tag the release
git tag v0.1.5
git push origin main --tags
```

## Testing Changes

### Local Plugin Testing

After modifying hook scripts, reload them in Claude Code:

```bash
# Method 1: Update the plugin (preferred)
claude plugin update session-logger@dazzle-claude-plugins

# Method 2: Full reinstall (if update doesn't work)
claude plugin marketplace remove dazzle-claude-plugins
claude plugin marketplace add "./"
claude plugin install session-logger@dazzle-claude-plugins

# IMPORTANT: Always restart Claude Code session after updating
# Hooks are loaded at session start
```

### Verifying Hook Loading

1. **Check debug log:**
   ```bash
   tail -f ~/.claude/logs/hook-debug.log
   ```

2. **Use /sessioninfo command** (if installed):
   ```
   > /sessioninfo
   Session ID: abc123...
   Session Name: my-project
   ```

3. **Check sesslog output:**
   ```bash
   ls -la ~/.claude/sesslogs/
   cat ~/.claude/sesslogs/*/.*sesslog*.log
   ```

### Testing Specific Features

| Feature | How to Test |
|---------|-------------|
| Grep logging | Run a Grep tool, check for `pattern \| "glob"` format |
| Write/Edit preview | Write a file, check for `← "content..."` in log |
| Agent context | Use Task tool with Explore, check for `Bash\|Explore:` |
| Auto-naming | Start session in a project folder, check directory name |

## Debugging

### Hook Debug Log

All hook activity is logged to:
```
~/.claude/logs/hook-debug.log
```

Add debug statements in `log-command.py`:
```python
debug_log(f"My debug message: {variable}")
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Stale plugin version | Remove marketplace, re-add, reinstall |
| Hook not firing | Check hooks.json path, restart session |
| Permission errors | Check file permissions in ~/.claude/ |
| Unicode errors | Ensure UTF-8 encoding in file operations |

### Session State Files

Session state is persisted in `~/.claude/session-states/`:
- `{id}.json` - Full session state
- `{id}.name-cache` - Cached session name
- `{id}.run` - Current run number
- `{id}.started` - Session start marker

## Code Style

- Python 3.9+ compatible
- Use type hints where practical
- Keep functions focused and documented
- Use `debug_log()` for troubleshooting output
- Handle cross-platform paths via `dazzle_filekit`

## Dependencies

- **dazzle-filekit** - Cross-platform path normalization and symlink creation
  ```bash
  pip install dazzle-filekit
  ```

## Pull Request Checklist

- [ ] Code changes tested locally
- [ ] Version bumped with `sync-versions.py`
- [ ] CHANGELOG.md updated
- [ ] All versions in sync (`--check` passes)
- [ ] Documentation updated if needed
- [ ] No sensitive data in commits
