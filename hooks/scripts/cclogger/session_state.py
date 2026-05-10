"""Session-state JSON persistence + transcript symlink + shell-type detection.

Holds the on-disk session state (sessions-index.json fallback, per-session
.json file for cross-process state sharing), creates the transcript symlink
for easy discovery, and pulls together a SessionContext (shell + name +
session_id + username) for filename construction.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dazzle_filekit import normalize_cross_platform_path, create_symlink

from cclogger.debug import debug_log
from cclogger.models import SessionContext, ToolInfo
from cclogger.session_naming import get_session_name


# ============================================================================
# Session State File Management
# ============================================================================


def get_sessions_index_path(transcript_path: str) -> Optional[str]:
    """Get the sessions-index.json path from transcript path."""
    if not transcript_path:
        return None
    transcript_file = normalize_cross_platform_path(transcript_path)
    sessions_index = transcript_file.parent / "sessions-index.json"
    if sessions_index.exists():
        return str(sessions_index)
    return None


def write_session_state(
    session_id: str,
    transcript_path: str,
    cwd: str,
    sesslog_dir: Optional[Path],
    current_name: Optional[str],
) -> None:
    """Write session state to ~/.claude/session-states/{session_id}.json.

    This enables commands (like /renameAI) to access session context
    that is only authoritatively available to hooks.
    """
    state_dir = Path.home() / ".claude" / "session-states"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{session_id}.json"

    # Preserve original_cwd from existing state (set once, never changes)
    original_cwd = cwd
    if state_file.exists():
        try:
            existing = json.loads(state_file.read_text())
            original_cwd = existing.get("original_cwd", existing.get("cwd", cwd))
        except Exception:
            pass

    state = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "sessions_index_path": get_sessions_index_path(transcript_path),
        "sesslog_dir": str(sesslog_dir) if sesslog_dir else None,
        "original_cwd": original_cwd,
        "cwd": cwd,
        "current_name": current_name,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    # Atomic write: write to temp file, then rename
    temp_file = state_file.with_suffix(".tmp")
    try:
        temp_file.write_text(json.dumps(state, indent=2))
        temp_file.replace(state_file)
        debug_log(f"Wrote session state to {state_file}")
    except Exception as e:
        debug_log(f"Failed to write session state: {e}")


def read_session_state(session_id: str) -> Optional[dict]:
    """Read session state from ~/.claude/session-states/{session_id}.json."""
    state_file = Path.home() / ".claude" / "session-states" / f"{session_id}.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception as e:
            debug_log(f"Failed to read session state: {e}")
    return None


def ensure_transcript_symlink(sesslog_dir: Path, transcript_path: str) -> bool:
    """Create a symlink to the transcript file in the session directory.

    Creates: {sesslog_dir}/transcript.jsonl -> {transcript_path}

    This makes it easier to find the transcript file from the sesslog directory.
    The symlink is only created if it doesn't already exist.

    Args:
        sesslog_dir: The session log directory
        transcript_path: Path to the transcript .jsonl file

    Returns:
        True if symlink exists or was created, False on error
    """
    if not transcript_path:
        debug_log("No transcript path provided, skipping symlink")
        return False

    symlink_path = sesslog_dir / "transcript.jsonl"

    # Check if symlink already exists and points to the right target
    if symlink_path.is_symlink():
        try:
            existing_target = os.readlink(symlink_path)
            # Normalize paths for comparison
            transcript_normalized = normalize_cross_platform_path(transcript_path)
            existing_normalized = normalize_cross_platform_path(existing_target)
            if transcript_normalized == existing_normalized:
                debug_log(f"Transcript symlink already exists: {symlink_path}")
                return True
            # Different target - remove and recreate
            debug_log(f"Transcript symlink points to wrong target, recreating")
            symlink_path.unlink()
        except Exception as e:
            debug_log(f"Error checking existing symlink: {e}")
            return False

    # Skip if regular file exists at symlink path
    if symlink_path.exists() and not symlink_path.is_symlink():
        debug_log(f"Cannot create symlink - regular file exists: {symlink_path}")
        return False

    # Normalize the transcript path
    transcript_file = normalize_cross_platform_path(transcript_path)

    # Create the symlink
    try:
        result = create_symlink(transcript_file, symlink_path)
        if result:
            debug_log(f"Created transcript symlink: {symlink_path} -> {transcript_file}")
        else:
            debug_log(f"Failed to create transcript symlink (create_symlink returned False)")
        return result
    except Exception as e:
        # Don't let symlink failure block logging
        debug_log(f"Error creating transcript symlink: {e}")
        return False


# ============================================================================
# Shell Type Detection
# ============================================================================


def detect_shell_type() -> str:
    """Detect the current shell type in a lightweight, cross-platform way."""
    # SHELL is reliable on POSIX systems (Linux, macOS, WSL)
    shell_path = os.environ.get("SHELL")
    if shell_path:
        return Path(shell_path).name

    # On Windows, SHELL is not standard - use other indicators
    if os.name == "nt":
        # COMSPEC points to default command processor (usually cmd.exe)
        comspec = os.environ.get("COMSPEC", "")
        if "cmd.exe" in comspec.lower():
            return "cmd"

        # PowerShell sets this internal env var
        if os.environ.get("PSModulePath"):
            return "powershell"

        # Generic Windows shell fallback
        return "win_shell"

    return "unknown"


def detect_tmux_session() -> Optional[str]:
    """Detect tmux session name if running in tmux."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def build_session_context(tool_info: ToolInfo) -> SessionContext:
    """Build the session context for file naming."""
    username = os.environ.get("USER") or os.environ.get("USERNAME", "unknown")
    session_name = get_session_name(tool_info.session_id, tool_info.transcript_path)

    # Check for tmux
    tmux_session = detect_tmux_session()
    if tmux_session:
        shell_type = f"tmux_{tmux_session}"
    else:
        shell_type = detect_shell_type()

    return SessionContext(
        shell_type=shell_type,
        session_name=session_name,
        session_id=tool_info.session_id,
        username=username,
    )
