"""Single resolver for the Claude data directory and the logger's subpaths.

Every file the logger writes lives under one base directory. Historically
that was hard-coded as ``Path.home() / ".claude"`` in ~20 places, which
ignored relocated setups (containers, host mounts, worktree-isolated
agents) where Claude Code's data directory is moved elsewhere.

This module is the one owner of that base path. It honors relocation the
SAME way claude-session-backup (csb) does, so the companion pair never
drifts -- csb backs up and searches exactly the files the logger writes,
so both must agree on where the Claude directory is:

    precedence: CLAUDE_DIR  >  CLAUDE_CONFIG_DIR  >  ~/.claude

``CLAUDE_CONFIG_DIR`` is Claude Code's own relocation variable (set in the
hook environment when the data directory is moved); ``CLAUDE_DIR`` is the
csb-aligned override. The logger has no CLI flag or config key for the base
dir, so those (higher-precedence in csb) rungs simply don't apply here --
but the two env rungs match csb exactly.

Accessors are functions (not module constants) so they re-resolve per call
-- which keeps tests honest (``monkeypatch.setenv``) and makes relocation
work even for any long-lived caller.
"""

from __future__ import annotations

import os
from pathlib import Path


def claude_dir() -> Path:
    """The Claude data directory: ``CLAUDE_DIR`` > ``CLAUDE_CONFIG_DIR`` > ``~/.claude``."""
    env = os.environ.get("CLAUDE_DIR") or os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def session_states() -> Path:
    """``<claude_dir>/session-states`` -- state JSON, name-cache, convo-cursor, .source."""
    return claude_dir() / "session-states"


def sesslogs() -> Path:
    """``<claude_dir>/sesslogs`` -- per-session logger transcript folders."""
    return claude_dir() / "sesslogs"


def logs() -> Path:
    """``<claude_dir>/logs`` -- hook debug log + throttle sentinels."""
    return claude_dir() / "logs"


def captures() -> Path:
    """``<claude_dir>/captures`` -- bash failure stdout/stderr captures."""
    return claude_dir() / "captures"


def plugins_settings() -> Path:
    """``<claude_dir>/plugins/settings`` -- user plugin settings (session-logger.json)."""
    return claude_dir() / "plugins" / "settings"


def global_config() -> Path:
    """``<claude_dir>/claude-history.json`` -- the global logger config file."""
    return claude_dir() / "claude-history.json"


def session_config(session_context: str) -> Path:
    """``<claude_dir>/claude-history-<ctx>.json`` -- the per-session config file."""
    return claude_dir() / f"claude-history-{session_context}.json"
