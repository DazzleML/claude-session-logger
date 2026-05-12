"""Debug logging + dazzle-filekit auto-install + unknown-tool warning throttle.

Foundation module — depends only on stdlib. Other cclogger modules import
debug_log from here. _ensure_dazzle_filekit() is invoked once by
cclogger/__init__.py so that downstream modules can `from dazzle_filekit
import ...` without each one bootstrapping the install.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _ensure_dazzle_filekit():
    """Auto-install dazzle-filekit if missing (e.g. running inside a venv)."""
    try:
        import dazzle_filekit  # noqa: F401
        return
    except ImportError:
        pass

    # Avoid retrying on every hook call if install previously failed
    sentinel = Path.home() / ".claude" / "logs" / ".dazzle_filekit_install_failed"
    if sentinel.exists():
        # Check age -- retry after 1 hour in case issue was transient
        try:
            age_seconds = (datetime.now() - datetime.fromtimestamp(sentinel.stat().st_mtime)).total_seconds()
            if age_seconds < 3600:
                raise ImportError("dazzle-filekit install previously failed (retry in <1hr)")
        except (OSError, ValueError):
            pass  # Sentinel unreadable, retry install

    # Escalating install strategies:
    # 1. Normal pip (Windows, Ubuntu 22.04, venvs)
    # 2. --user (some systems where global is restricted)
    # 3. --break-system-packages (Ubuntu 24.04+ with PEP 668)
    pkg = "dazzle-filekit>=0.2.1"
    strategies = [
        [sys.executable, "-m", "pip", "install", "--quiet", pkg],
        [sys.executable, "-m", "pip", "install", "--quiet", "--user", pkg],
        [sys.executable, "-m", "pip", "install", "--quiet", "--break-system-packages", pkg],
    ]

    installed = False
    for cmd in strategies:
        try:
            subprocess.check_call(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            )
            installed = True
            break
        except Exception:
            continue

    if installed:
        sentinel.unlink(missing_ok=True)
    else:
        # Mark failure to avoid hammering pip on every hook call
        try:
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.touch()
        except OSError:
            pass
        raise ImportError("Failed to auto-install dazzle-filekit")


# Debug logging - use persistent location under ~/.claude
DEBUG_LOG = Path.home() / ".claude" / "logs" / "hook-debug.log"

# Throttle directory for "unknown tool encountered" warnings. Each unknown
# tool name gets a sentinel file on first sighting; subsequent invocations
# (across hook subprocesses, not just within one process) skip the warning.
# Delete the directory or individual sentinels to re-trigger warnings.
UNKNOWN_TOOL_WARN_DIR = Path.home() / ".claude" / "logs" / ".unknown_tool_warnings"
# Phase 2+3 Step 10: parallel sentinel directory for unknown role names.
# When a LogEntry's role is not in the closed ROLES enum, formatters render
# it as `??:<role>` (visible in logs) AND emit a one-time debug-log warning
# via this helper. Sibling directory keeps the unknown-tool and unknown-role
# warning streams independent.
UNKNOWN_ROLE_WARN_DIR = Path.home() / ".claude" / "logs" / ".unknown_role_warnings"


def _warn_unknown_tool_once(tool_name: str, fields: list[str]) -> None:
    """Log a one-time warning when an unknown tool's content extraction fails.

    Uses a sentinel file (cross-process throttling) so that multiple hook
    invocations don't spam hook-debug.log. Sentinel creation is atomic
    (O_CREAT|O_EXCL via mode "x") to prevent the TOCTOU race where two
    parallel hook subprocesses both pass an `exists()` check and then both
    write the warning. Best-effort — silent on errors so the hook itself
    never breaks.
    """
    try:
        UNKNOWN_TOOL_WARN_DIR.mkdir(parents=True, exist_ok=True)
        # Sanitize tool name for filesystem safety
        safe_name = re.sub(r"[^A-Za-z0-9_\-.]", "_", tool_name)
        sentinel = UNKNOWN_TOOL_WARN_DIR / f"{safe_name}.warned"
        # Atomic exclusive create: succeeds exactly once across all processes
        try:
            sentinel.open("x").close()
        except FileExistsError:
            return  # Another process won the race; warning already logged
        debug_log(
            f"Unknown tool '{tool_name}' encountered with no extractable "
            f"content - input fields: {fields} - "
            f"add a specific handler in get_command_content() or expand the "
            f"fallback list in the else branch"
        )
    except Exception:
        pass  # Throttling is best-effort; never break the hook


def _warn_unknown_role_once(role: str) -> None:
    """One-time debug-log warning for a role not in the closed ROLES enum.

    Mirrors the v0.2.1 unknown-tool throttled-warning pattern with a sibling
    sentinel directory so the two warning streams stay independent. The role
    will already render as `??:<role>` in formatters; this helper surfaces a
    debug-log breadcrumb so we can add the role to ROLES (and its label to
    ROLE_LABELS) when one shows up in real-world traffic.

    Best-effort — silent on errors so the hook itself never breaks.
    """
    try:
        UNKNOWN_ROLE_WARN_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_\-.:]", "_", role)
        sentinel = UNKNOWN_ROLE_WARN_DIR / f"{safe_name}.warned"
        try:
            sentinel.open("x").close()
        except FileExistsError:
            return
        debug_log(
            f"Unknown role '{role}' rendered as '??:{role}' in logs - "
            f"add to ROLES set (and ROLE_LABELS for a display label) in "
            f"cclogger/models.py if this shows up regularly"
        )
    except Exception:
        pass


def debug_log(message: str) -> None:
    """Append debug message to log file."""
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"{datetime.now()}: {message}\n")
    except Exception:
        pass
