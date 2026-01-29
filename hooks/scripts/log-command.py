#!/usr/bin/env python3
"""Claude Code session command history logger.

Orthogonal control: Verbosity (0-4) + Context flags (datetime/pwd) + Tool filtering

Format examples:
  Level 0: {command}
  Level 1: {optional_datetime}{command}{optional_pwd}
  Level 2: {optional_datetime}{tool command}{optional_pwd}
  Level 3: {optional_datetime}{tool command description}{optional_pwd}
  Level 4: {optional_datetime}{tool command full_json}{optional_pwd}
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dazzle_filekit import normalize_cross_platform_path, create_symlink

# Debug logging - use persistent location under ~/.claude
DEBUG_LOG = Path.home() / ".claude" / "logs" / "hook-debug.log"


def debug_log(message: str) -> None:
    """Append debug message to log file."""
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a") as f:
            f.write(f"{datetime.now()}: {message}\n")
    except Exception:
        pass


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class ToolInfo:
    """Information extracted from Claude Code's JSON input."""

    name: str
    input: dict[str, Any]
    description: str
    session_id: str
    transcript_path: str
    raw_json: dict[str, Any]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ToolInfo:
        """Create ToolInfo from JSON input."""
        return cls(
            name=data.get("tool_name", ""),
            input=data.get("tool_input", {}),
            description=data.get("tool_description", ""),
            session_id=data.get("session_id", "unknown"),
            transcript_path=data.get("transcript_path", ""),
            raw_json=data,
        )


@dataclass
class Config:
    """Logger configuration with all settings."""

    verbosity: int = 2
    datetime_mode: str = "full"  # "full", "date", "none"
    pwd_enabled: bool = False
    filter_include: list[str] = field(default_factory=list)

    # Action-only settings by category
    action_only: dict[str, bool] = field(
        default_factory=lambda: {
            "io": False,
            "bash": False,
            "todo": True,
            "task": False,
            "system": False,
            "meta": False,
            "search": False,
        }
    )

    # Per-tool overrides ("true", "false", or "use_category")
    action_only_overrides: dict[str, str] = field(
        default_factory=lambda: {"TodoWrite": "use_category"}
    )

    # Failure capture settings
    failure_capture_enabled: bool = False
    failure_capture_stderr: bool = True
    failure_capture_max_lines: int = 50


@dataclass
class SessionContext:
    """Session identification for file naming."""

    shell_type: str
    session_name: Optional[str]
    session_id: str
    username: str

    def get_filename_context(self) -> str:
        """Generate filename context string.

        Format (with name): {shell}__{name}__{session_id}_{username}
        Format (without):   {shell}_{session_id}_{username}
        """
        if self.session_name:
            return f"{self.shell_type}__{self.session_name}__{self.session_id}_{self.username}"
        else:
            return f"{self.shell_type}_{self.session_id}_{self.username}"

    def get_task_filename_context(self) -> str:
        """Generate task filename context with consistent double-underscore separators.

        Format (with name): {shell}__{name}__{session_id}__{username}
        Format (without):   {shell}__{session_id}__{username}
        """
        if self.session_name:
            return f"{self.shell_type}__{self.session_name}__{self.session_id}__{self.username}"
        else:
            return f"{self.shell_type}__{self.session_id}__{self.username}"


@dataclass
class LogEntry:
    """Represents a formatted log entry."""

    timestamp: Optional[datetime]
    tool_name: str
    content: str
    pwd: Optional[str]
    is_failure: bool = False
    failure_reason: Optional[str] = None
    error_output: Optional[str] = None


# ============================================================================
# Tool Categorization
# ============================================================================

TOOL_CATEGORIES: dict[str, str] = {
    # Core execution
    "Bash": "bash",
    # File system queries
    "LS": "system",
    "Glob": "system",
    "Grep": "system",
    "Read": "system",
    # File I/O
    "Write": "io",
    "Edit": "io",
    "MultiEdit": "io",
    "NotebookEdit": "io",
    # Task management
    "TodoWrite": "todo",
    "TaskCreate": "task",
    "TaskUpdate": "task",
    "TaskList": "task",
    "TaskGet": "task",
    # Meta/agents
    "Task": "meta",
    # Web interaction
    "WebSearch": "search",
    "WebFetch": "search",
    # User interaction (stubs)
    "AskUserQuestion": "ui",
    "Skill": "skill",
}


def categorize_tool(tool_name: str) -> str:
    """Map tool name to category."""
    # Check for MCP tools (mcp__servername__toolname format)
    if tool_name.startswith("mcp__"):
        return "mcp"

    category = TOOL_CATEGORIES.get(tool_name)
    if category:
        return category

    # Unknown tool - log for visibility and return "other"
    debug_log(f"Unknown tool encountered: {tool_name}, categorizing as 'other'")
    return "other"


# ============================================================================
# Session Name Detection
# ============================================================================


def get_session_name(session_id: str, transcript_path: str) -> Optional[str]:
    """Extract user-given session name from transcript or sessions-index.json.

    Always checks transcript for the LATEST custom-title entry (last one wins),
    since sessions can be renamed multiple times via /rename or /renameAI.
    Cache is updated when a name is found, but never used to short-circuit
    the transcript check (to ensure renames are detected immediately).
    """
    state_dir = Path.home() / ".claude" / "session-states"
    cache_file = state_dir / f"{session_id}.name-cache"
    session_name = None

    if transcript_path:
        transcript_file = normalize_cross_platform_path(transcript_path)

        # Method 1: Check transcript .jsonl for custom-title entries
        # Iterate through ALL entries - last one wins (most recent rename)
        if transcript_file.exists():
            try:
                with open(transcript_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if '"type":"custom-title"' in line or '"type": "custom-title"' in line:
                            try:
                                entry = json.loads(line)
                                if entry.get("customTitle"):
                                    session_name = entry["customTitle"]
                            except json.JSONDecodeError:
                                pass
            except Exception:
                pass

        # Method 2: Fallback to sessions-index.json (if no custom-title in transcript)
        if not session_name:
            sessions_index = transcript_file.parent / "sessions-index.json"
            if sessions_index.exists():
                try:
                    with open(sessions_index, "r", encoding="utf-8") as f:
                        index_data = json.load(f)
                        for entry in index_data.get("entries", []):
                            if entry.get("sessionId") == session_id:
                                session_name = entry.get("customTitle")
                                break
                except Exception:
                    pass

    # Method 3: Fallback to cache (if transcript/index reads failed)
    if not session_name and cache_file.exists():
        try:
            cached_name = cache_file.read_text().strip()
            if cached_name:
                session_name = cached_name
        except Exception:
            pass

    # Update cache with latest name (for debugging/inspection)
    if session_name:
        try:
            cache_file.write_text(session_name)
        except Exception:
            pass

    return session_name


# Generic folder names that shouldn't become session names on their own
# These are still used as fallback components in path-based names
GENERIC_FOLDER_NAMES = {
    "home", "user", "users", "code", "projects", "project", "work",
    "dev", "development", "src", "source", "app", "apps", "local",
    "current", "main", "master", "opt", "var", "tmp", "temp",
    "desktop", "documents", "downloads", "repos", "repository",
    "github", "gitlab", "bitbucket", "workspace", "workspaces",
}

# Drive letters (Windows) - these alone aren't useful
DRIVE_LETTERS = {"c", "d", "e", "f", "g", "h", "z"}


def _sanitize_folder_name(name: str) -> str:
    """Sanitize a folder name for use in session names."""
    import re
    # Remove special chars, replace spaces/underscores with hyphens
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '-', name.lower())
    sanitized = re.sub(r'-+', '-', sanitized)  # Collapse multiple hyphens
    return sanitized.strip('-')


def derive_session_name_from_cwd(cwd: str) -> Optional[str]:
    """Derive a session name from the working directory.

    Strategy:
    1. If current folder is non-generic, use it alone (e.g., "my-project")
    2. Otherwise, walk up to find the nearest non-generic ancestor,
       then use path from there down (e.g., "extreme--documents", "my-project--local")
    3. Include drive letters in path-based names for context (e.g., "C--code")

    This ensures we always get SOME name rather than leaving unnamed,
    and path-based names provide useful context without including every parent folder.

    Args:
        cwd: Current working directory path

    Returns:
        A sanitized session name, or None only if path is empty/invalid
    """
    if not cwd:
        return None

    path = normalize_cross_platform_path(cwd)

    # Use path.parts to get all components including drive letter
    # e.g., ('C:\\', 'code', 'project') or ('/', 'home', 'user')
    try:
        all_parts = path.parts
    except AttributeError:
        # Fallback for mock objects - split manually
        path_str = str(path).replace('\\', '/')
        all_parts = [p for p in path_str.split('/') if p]

    # Collect last 4 meaningful parts with metadata
    parts = []  # List of (sanitized, raw, is_drive) tuples
    for part in all_parts[-4:]:
        # Clean up drive letter format (e.g., "C:\\" -> "C", "C:" -> "C")
        raw = part.rstrip(':\\/')
        sanitized = _sanitize_folder_name(raw)
        if sanitized:
            is_drive = sanitized in DRIVE_LETTERS
            parts.append((sanitized, raw.lower(), is_drive))

    if not parts:
        debug_log("No usable path parts found")
        return None

    # Strategy 1: If current folder is non-generic (and not a drive letter), use it alone
    current_name, current_raw, current_is_drive = parts[-1]
    if (current_raw not in GENERIC_FOLDER_NAMES and
        not current_is_drive and
        len(current_name) >= 3):
        debug_log(f"Using current folder name: '{current_name}'")
        return current_name[:50]

    # Strategy 2: Find the nearest non-generic ancestor (excluding drive letters),
    # then use path from there down (including drive letter if it's the start)
    start_idx = 0
    for i in range(len(parts) - 2, -1, -1):  # Start from second-to-last, go to 0
        _, raw, is_drive = parts[i]
        if raw not in GENERIC_FOLDER_NAMES and not is_drive:
            start_idx = i
            break

    # Build path from start_idx to end
    path_parts = [s for s, r, d in parts[start_idx:] if len(s) >= 1]
    if path_parts:
        path_name = "--".join(path_parts)
        # Truncate if too long, but keep it meaningful
        if len(path_name) > 50:
            path_name = path_name[:50].rsplit("--", 1)[0]
        debug_log(f"Using path-based name: '{path_name}'")
        return path_name

    debug_log("Could not derive session name from path")
    return None


def apply_auto_name_on_session_start(
    session_id: str,
    transcript_path: str,
    cwd: str,
    hook_event_name: str
) -> Optional[str]:
    """Apply auto-naming from folder on SessionStart if session is unnamed.

    Only applies if:
    - This is a SessionStart hook
    - Session has no custom-title yet
    - Working directory name is suitable

    The auto-name is stored in the name-cache file so subsequent hooks
    can use it for directory/file naming.

    Args:
        session_id: The session ID
        transcript_path: Path to the transcript file
        cwd: Current working directory
        hook_event_name: The hook event name

    Returns:
        The auto-generated name if applied, None otherwise
    """
    # Only apply on SessionStart
    if hook_event_name != "SessionStart":
        return None

    # Check if session already has a name
    existing_name = get_session_name(session_id, transcript_path)
    if existing_name:
        debug_log(f"Session already has name '{existing_name}', skipping auto-name")
        return None

    # Derive name from folder
    auto_name = derive_session_name_from_cwd(cwd)
    if not auto_name:
        return None

    # Store in cache file so subsequent hooks pick it up
    state_dir = Path.home() / ".claude" / "session-states"
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_file = state_dir / f"{session_id}.name-cache"

    try:
        cache_file.write_text(auto_name)
        debug_log(f"Applied auto-name '{auto_name}' for session {session_id}")
        return auto_name
    except Exception as e:
        debug_log(f"Failed to write auto-name to cache: {e}")
        return None


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


# ============================================================================
# Configuration Loading
# ============================================================================


def load_config_file(path: Path) -> dict[str, Any]:
    """Load a JSON config file, returning empty dict on failure."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def merge_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge two config dicts, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse a value as boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if isinstance(value, int):
        return value != 0
    return default


def load_configuration(session_context: str) -> Config:
    """Load configuration with proper precedence.

    Priority: Environment Variables > Session Config > Global Config > Defaults
    """
    home = Path.home()
    global_config_path = home / ".claude" / "claude-history.json"
    session_config_path = home / ".claude" / f"claude-history-{session_context}.json"

    # Load and merge config files
    global_config = load_config_file(global_config_path)
    session_config = load_config_file(session_config_path)
    file_config = merge_configs(global_config, session_config)

    # Start with defaults
    config = Config()

    # Apply file config
    if "verbosity" in file_config:
        try:
            v = int(file_config["verbosity"])
            if 0 <= v <= 4:
                config.verbosity = v
        except (ValueError, TypeError):
            pass

    datetime_setting = file_config.get("datetime", "full")
    if datetime_setting in ("full", "true", "1", "yes", True):
        config.datetime_mode = "full"
    elif datetime_setting == "date":
        config.datetime_mode = "date"
    elif datetime_setting in ("false", "0", "no", False, "none"):
        config.datetime_mode = "none"

    config.pwd_enabled = parse_bool(file_config.get("pwd", False))

    # Filter include list
    filter_config = file_config.get("filter", {})
    if isinstance(filter_config, dict):
        include_list = filter_config.get("include", [])
        if isinstance(include_list, list):
            config.filter_include = include_list

    # Action-only settings
    action_only_config = file_config.get("action_only", {})
    categories = action_only_config.get("categories", {})
    for cat in config.action_only.keys():
        if cat in categories:
            config.action_only[cat] = parse_bool(categories[cat])

    overrides = action_only_config.get("overrides", {})
    for tool, value in overrides.items():
        config.action_only_overrides[tool] = str(value)

    # Failure capture
    failure_config = file_config.get("failure_capture", {})
    config.failure_capture_enabled = parse_bool(failure_config.get("enabled", False))
    config.failure_capture_stderr = parse_bool(failure_config.get("capture_stderr", True))
    try:
        max_lines = int(failure_config.get("max_stderr_lines", 50))
        config.failure_capture_max_lines = max(1, min(1000, max_lines))
    except (ValueError, TypeError):
        pass

    # Environment variable overrides (highest priority)
    env_verbosity = os.environ.get("CLAUDE_HISTORY_VERBOSITY")
    if env_verbosity:
        try:
            v = int(env_verbosity)
            if 0 <= v <= 4:
                config.verbosity = v
        except ValueError:
            pass

    env_datetime = os.environ.get("CLAUDE_HISTORY_DATETIME")
    if env_datetime:
        if env_datetime in ("full", "true", "1", "yes"):
            config.datetime_mode = "full"
        elif env_datetime == "date":
            config.datetime_mode = "date"
        elif env_datetime in ("false", "0", "no", "none"):
            config.datetime_mode = "none"

    env_pwd = os.environ.get("CLAUDE_HISTORY_PWD")
    if env_pwd:
        config.pwd_enabled = parse_bool(env_pwd)

    env_filter = os.environ.get("CLAUDE_HISTORY_FILTER")
    if env_filter:
        config.filter_include = [f.strip() for f in env_filter.split(",") if f.strip()]

    # Action-only environment overrides
    for cat in config.action_only.keys():
        env_var = f"CLAUDE_HISTORY_ACTION_ONLY_{cat.upper()}"
        env_val = os.environ.get(env_var)
        if env_val:
            config.action_only[cat] = parse_bool(env_val)

    env_todowrite = os.environ.get("CLAUDE_HISTORY_ACTION_ONLY_TODOWRITE")
    if env_todowrite:
        config.action_only_overrides["TodoWrite"] = env_todowrite

    # Failure capture environment overrides
    env_failure_enabled = os.environ.get("CLAUDE_HISTORY_FAILURE_ENABLED")
    if env_failure_enabled:
        config.failure_capture_enabled = parse_bool(env_failure_enabled)

    env_failure_stderr = os.environ.get("CLAUDE_HISTORY_FAILURE_STDERR")
    if env_failure_stderr:
        config.failure_capture_stderr = parse_bool(env_failure_stderr)

    env_failure_max = os.environ.get("CLAUDE_HISTORY_FAILURE_MAX_LINES")
    if env_failure_max:
        try:
            config.failure_capture_max_lines = max(1, min(1000, int(env_failure_max)))
        except ValueError:
            pass

    return config


# ============================================================================
# Filtering Logic
# ============================================================================


def should_log_tool(tool_name: str, config: Config) -> bool:
    """Check if tool should be logged based on filtering."""
    # If no filter specified, log everything
    if not config.filter_include:
        return True

    category = categorize_tool(tool_name)
    return category in config.filter_include


def should_use_action_only(tool_name: str, config: Config) -> bool:
    """Check if tool should use action-only mode (show only tool name)."""
    # Check for specific tool override first
    if tool_name in config.action_only_overrides:
        override = config.action_only_overrides[tool_name]
        if override != "use_category":
            return parse_bool(override)

    # Use category default
    category = categorize_tool(tool_name)
    return config.action_only.get(category, False)


# ============================================================================
# Content Extraction
# ============================================================================


def get_task_content(tool_name: str, raw_json: dict[str, Any]) -> str:
    """Extract task-specific content for Task* tools."""
    tool_input = raw_json.get("tool_input", {})
    tool_response = raw_json.get("tool_response", {})

    if tool_name == "TaskCreate":
        subject = tool_input.get("subject", "(no subject)")
        description = tool_input.get("description", "")[:100]

        # Extract task ID from tool_response
        task_id = ""
        if isinstance(tool_response, dict):
            task_data = tool_response.get("task", {})
            if isinstance(task_data, dict):
                task_id = task_data.get("id", "")

        id_part = f" #{task_id}" if task_id else ""

        if description:
            return f"CREATE{id_part}: {subject} | {description}..."
        return f"CREATE{id_part}: {subject}"

    elif tool_name == "TaskUpdate":
        task_id = tool_input.get("taskId", "?")
        status = tool_input.get("status", "")
        subject = tool_input.get("subject", "")
        active_form = tool_input.get("activeForm", "")

        # Get status change info from response
        from_status = ""
        if isinstance(tool_response, dict):
            status_change = tool_response.get("statusChange", {})
            if isinstance(status_change, dict):
                from_status = status_change.get("from", "")

        output = f"UPDATE: #{task_id}"
        if status:
            if from_status:
                output += f": {from_status} -> {status}"
            else:
                output += f" -> {status}"
        if subject:
            output += f" | title='{subject}'"
        if active_form:
            output += f" | {active_form}"

        return output

    elif tool_name == "TaskList":
        return "LIST"

    elif tool_name == "TaskGet":
        task_id = tool_input.get("taskId", "?")
        return f"GET: #{task_id}"

    return tool_name


def get_command_content(tool_info: ToolInfo) -> str:
    """Extract command content based on tool type."""
    tool_input = tool_info.input

    if tool_info.name == "Bash":
        return tool_input.get("command", "")

    elif tool_info.name in ("Read", "Write", "Edit", "MultiEdit"):
        path = tool_input.get("file_path", "")
        return f'"{path}"' if path else ""

    elif tool_info.name == "TodoWrite":
        todos = tool_input.get("todos", [])
        return json.dumps(todos, separators=(",", ":"))

    elif tool_info.name == "LS":
        path = tool_input.get("path", "")
        return f'"{path}"' if path else ""

    elif tool_info.name == "Glob":
        return tool_input.get("pattern", "")

    elif tool_info.name == "Grep":
        return tool_input.get("pattern", "")

    elif tool_info.name in ("WebSearch", "WebFetch"):
        return tool_input.get("url") or tool_input.get("query", "")

    elif tool_info.name == "Task":
        return tool_input.get("prompt", "")

    elif tool_info.name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        return get_task_content(tool_info.name, tool_info.raw_json)

    else:
        # For unknown tools, try common field names
        for field in ("pattern", "url", "prompt", "query", "content"):
            if field in tool_input:
                return str(tool_input[field])
        return ""


# ============================================================================
# Entry Generation
# ============================================================================


def format_datetime(mode: str, timestamp: Optional[datetime] = None) -> str:
    """Format datetime string based on mode.

    Args:
        mode: "full", "date", or "none"
        timestamp: The datetime to format. If None, uses datetime.now() (legacy fallback).
    """
    ts = timestamp or datetime.now()
    if mode == "date":
        return f"[[{ts.strftime('%Y-%m-%d')}]] "
    elif mode == "full":
        return f"[[{ts.strftime('%Y-%m-%d %H:%M:%S')}]] "
    return ""


def generate_entry(tool_info: ToolInfo, config: Config, command_content: str,
                   event_time: datetime) -> str:
    """Generate formatted log entry based on configuration."""
    datetime_part = format_datetime(config.datetime_mode, event_time)

    pwd_part = ""
    if config.pwd_enabled:
        pwd_part = f' ["{os.getcwd()}"]'

    # Determine content based on verbosity and action-only
    if should_use_action_only(tool_info.name, config):
        content_part = tool_info.name
    else:
        if config.verbosity == 0:
            content_part = command_content
        elif config.verbosity == 1:
            content_part = command_content
        elif config.verbosity == 2:
            content_part = f"{tool_info.name}: {command_content}"
        elif config.verbosity == 3:
            if tool_info.description:
                content_part = f"{tool_info.name}: {command_content} {tool_info.description}"
            else:
                content_part = f"{tool_info.name}: {command_content}"
        elif config.verbosity == 4:
            tool_input_json = json.dumps(tool_info.input, separators=(",", ":"))
            content_part = f"{tool_info.name}: {command_content} {tool_input_json}"
        else:
            content_part = f"{tool_info.name}: {command_content}"

    return f"{datetime_part}{{{content_part} }}{pwd_part}"


# ============================================================================
# File Writing
# ============================================================================


def check_time_gap(file_path: Path, datetime_mode: str, event_time: datetime,
                   gap_seconds: int = 1800) -> bool:
    """Check if there's a 30+ minute gap since last entry.

    Args:
        file_path: Path to the log file to check
        datetime_mode: The datetime mode setting
        event_time: The current event's timestamp (for consistent comparison)
        gap_seconds: Number of seconds to consider a gap (default 30 minutes)
    """
    if datetime_mode == "none" or not file_path.exists():
        return False

    try:
        # Read last line
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if not lines:
                return False
            last_line = lines[-1]

        # Extract timestamp
        match = re.search(r"\[\[([^\]]+)\]\]", last_line)
        if not match:
            return False

        last_timestamp_str = match.group(1)

        # Parse timestamp - try both formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                last_time = datetime.strptime(last_timestamp_str, fmt)
                break
            except ValueError:
                continue
        else:
            return False

        # Calculate time difference using event_time (not datetime.now())
        time_diff = (event_time - last_time).total_seconds()
        return time_diff >= gap_seconds

    except Exception:
        return False


def atomic_append(file_path: Path, content: str, add_gap: bool = False) -> None:
    """Atomically append content to file using temp file + rename.

    Either succeeds completely or leaves file unchanged. On failure,
    writes to an overflow file (same name + .overflow.N) to preserve
    the entry without risking corruption of the main file.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Strip null bytes that could corrupt log file or confuse readers
    content = content.replace("\x00", "")

    temp_file = None
    try:
        # Create temp file in same directory (required for atomic rename)
        fd, temp_path = tempfile.mkstemp(
            suffix=".tmp", prefix=file_path.name + ".", dir=file_path.parent
        )
        temp_file = Path(temp_path)

        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            # Copy existing content (also strip null bytes)
            if file_path.exists():
                existing = file_path.read_text(encoding="utf-8").replace("\x00", "")
                f.write(existing)

            # Add gap marker if needed
            if add_gap:
                f.write("\n")

            # Add new content
            f.write(content + "\n")

        # Atomic rename
        shutil.move(str(temp_file), str(file_path))

    except Exception as e:
        # Atomic write failed - write to overflow file to preserve entry
        debug_log(f"Atomic append to {file_path.name} failed: {e}. Writing to overflow.")
        _write_to_overflow(file_path, content, add_gap)

    finally:
        # Always clean up temp file
        if temp_file and temp_file.exists():
            temp_file.unlink(missing_ok=True)


def _write_to_overflow(file_path: Path, content: str, add_gap: bool) -> None:
    """Write entry to overflow file when atomic write fails.

    Uses incrementing suffix: .overflow.1, .overflow.2, etc.
    Simple append (not atomic) but isolated from main file.
    """
    # Find next available overflow file number
    n = 1
    while True:
        overflow_path = file_path.parent / f"{file_path.name}.overflow.{n}"
        if not overflow_path.exists() or overflow_path.stat().st_size < 1_000_000:
            # Use this file (new or under 1MB)
            break
        n += 1
        if n > 100:
            # Safety limit - don't create infinite overflow files
            debug_log(f"Too many overflow files for {file_path.name}, entry dropped")
            return

    try:
        with open(overflow_path, "a", encoding="utf-8", newline="\n") as f:
            if add_gap:
                f.write("\n")
            f.write(content + "\n")
        debug_log(f"Entry written to overflow: {overflow_path.name}")
    except Exception as e:
        debug_log(f"Overflow write also failed: {e}. Entry lost.")


# ============================================================================
# File Reconciliation - Retroactive Session Name Renaming
# ============================================================================

# Session marker signature - used to count run numbers
SESSION_MARKER_SIGNATURE = "═══ SESSION"


# ============================================================================
# Session Directory Management
# ============================================================================


def sanitize_dirname(name: str, max_len: int = 50) -> str:
    """Sanitize session name for filesystem safety.

    Args:
        name: The session name to sanitize
        max_len: Maximum length for the name portion

    Returns:
        Filesystem-safe version of the name
    """
    # Replace characters that are problematic on Windows/Unix filesystems
    safe = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Also replace any control characters
    safe = re.sub(r'[\x00-\x1f]', '_', safe)
    # Truncate to max length
    return safe[:max_len]


def find_directory_by_guid(sesslog_base: Path, session_id: str) -> Optional[Path]:
    """Find any existing directory containing this session GUID.

    Returns the first matching directory, or None if not found.
    """
    try:
        for item in sesslog_base.iterdir():
            if item.is_dir() and session_id in item.name:
                return item
    except Exception:
        pass
    return None


def extract_name_from_directory(dir_path: Path, session_id: str) -> Optional[str]:
    """Extract session name from directory name.

    Directory format: {name}__{guid}_{user} or __{guid}_{user} (unnamed)
    Returns None if unnamed or cannot parse.
    """
    dir_name = dir_path.name
    if dir_name.startswith("__"):
        return None  # Unnamed directory

    # Pattern: {name}__{guid}_{user}
    match = re.match(rf"^(.+)__{re.escape(session_id)}_", dir_name)
    if match:
        return match.group(1)
    return None


def reconcile_session_directory(sesslog_base: Path, session_id: str,
                                  expected_name: Optional[str], username: str) -> tuple[Path, Optional[str]]:
    """Unified reconciliation for session directory and files.

    This function handles:
    1. Finding existing directory by GUID
    2. Renaming directory if name doesn't match expected
    3. Renaming files inside if directory was renamed
    4. Creating new directory if none exists

    Args:
        sesslog_base: Base sesslogs directory
        session_id: Session GUID
        expected_name: Expected session name (None if unnamed)
        username: Username

    Returns:
        Tuple of (session_directory_path, old_session_name_if_renamed)
    """
    # Build expected directory name
    expected_dir_name = build_session_directory(expected_name, session_id, username)
    expected_dir = sesslog_base / expected_dir_name

    # If expected directory already exists, we're done
    if expected_dir.exists():
        return expected_dir, None

    # Search for any directory with this session GUID
    existing_dir = find_directory_by_guid(sesslog_base, session_id)

    if existing_dir:
        # Directory exists but with different name - need to rename
        old_name = extract_name_from_directory(existing_dir, session_id)

        # Rename directory
        try:
            existing_dir.rename(expected_dir)
            debug_log(f"Renamed session directory: {existing_dir.name} -> {expected_dir_name}")

            # Rename files inside to match new session name (if we have a new name)
            if expected_name:
                _rename_files_for_session_change(
                    expected_dir,
                    old_name,  # May be None if was unnamed
                    expected_name,
                    session_id
                )

            return expected_dir, old_name
        except Exception as e:
            debug_log(f"Failed to rename session directory: {e}")
            # Fall back to using existing directory as-is
            return existing_dir, None

    # No existing directory - create new
    expected_dir.mkdir(parents=True, exist_ok=True)
    debug_log(f"Created session directory: {expected_dir_name}")
    return expected_dir, None


def _rename_files_for_session_change(directory: Path, old_session_name: Optional[str],
                                      new_session_name: str, session_id: str) -> None:
    """Rename all files in directory to reflect new session name.

    Handles both unnamed→named and named→renamed transitions.
    This is the file-level counterpart to directory renaming.
    """
    if not directory.exists():
        return

    for f in directory.iterdir():
        if not f.is_file():
            continue

        old_name = f.name
        new_name = None

        if old_session_name:
            # Named → Renamed: replace old name with new name
            if old_session_name in old_name:
                new_name = old_name.replace(old_session_name, new_session_name)
        else:
            # Unnamed → Named: insert name before GUID
            # Pattern: .type_shell_{guid}_{user}[.log] → .type_shell__{name}__{guid}_{user}[.log]
            pattern = rf"^(\.[\w]+_[\w.]+)_{re.escape(session_id)}_"
            match = re.match(pattern, old_name)
            if match:
                prefix = match.group(1)
                suffix = old_name[len(match.group(0))-1:]  # Keep _{user}... part
                new_name = f"{prefix}__{new_session_name}__{session_id}{suffix}"

        if new_name and new_name != old_name:
            new_path = directory / new_name
            if not new_path.exists():
                try:
                    f.rename(new_path)
                    debug_log(f"Renamed file: {old_name} -> {new_name}")
                except Exception as e:
                    debug_log(f"Failed to rename file {old_name}: {e}")


def build_session_directory(session_name: Optional[str], session_id: str,
                            username: str) -> str:
    """Build session directory name.

    Format (with name): {name}__{guid}_{user}
    Format (without):   __{guid}_{user}

    Args:
        session_name: The session name (may be None for unnamed sessions)
        session_id: The session GUID
        username: The username

    Returns:
        Directory name string (not full path)
    """
    if session_name:
        safe_name = sanitize_dirname(session_name)
        return f"{safe_name}__{session_id}_{username}"
    else:
        return f"__{session_id}_{username}"


def find_session_files(sesslog_dir: Path, session_id: str, prefix: str,
                       file_type: str) -> list[Path]:
    """Find all files for a given session ID and file type.

    Matches both named and unnamed files, with or without sequence numbers.
    Handles both old files (no extension) and new files (.log extension).
    """
    # Pattern matches (with optional .log extension):
    #   .{prefix}{type}_{shell}_{guid}_{user}[.log]              (unnamed)
    #   .{prefix}{type}_{shell}__{name}__{guid}_{user}[.log]     (named)
    #   .{prefix}{type}_{shell}__{name}--NNN__{guid}_{user}[.log] (named with sequence)
    pattern = re.compile(
        rf"^\.{re.escape(prefix)}{re.escape(file_type)}_[^_]+_.*{re.escape(session_id)}_\w+(\.log)?$"
    )

    matches = []
    try:
        for f in sesslog_dir.iterdir():
            if f.is_file() and pattern.match(f.name):
                matches.append(f)
    except Exception as e:
        debug_log(f"Error scanning sesslog_dir: {e}")

    return matches


def find_max_sequence(sesslog_dir: Path, prefix: str, file_type: str, shell: str,
                      session_name: str, session_id: str, username: str) -> int:
    """Find the highest existing sequence number (--NNN) for this session."""
    # Pattern: .{prefix}{type}_{shell}__{name}--NNN__{guid}_{user}[.log]
    pattern = re.compile(
        rf"^\.{re.escape(prefix)}{re.escape(file_type)}_{re.escape(shell)}__"
        rf"{re.escape(session_name)}--(\d{{3}})__{re.escape(session_id)}_{re.escape(username)}(\.log)?$"
    )

    max_seq = -1
    try:
        for f in sesslog_dir.iterdir():
            match = pattern.match(f.name)
            if match:
                seq = int(match.group(1))
                max_seq = max(max_seq, seq)
    except Exception:
        pass

    return max_seq


def build_filename(prefix: str, file_type: str, shell: str, session_name: Optional[str],
                   session_id: str, username: str, seq: Optional[int] = None) -> str:
    """Build a log filename with optional sequence number.

    Args:
        prefix: File prefix (e.g., "Python_" or "")
        file_type: "sesslog", "shell", or "tasks"
        shell: Shell type (e.g., "bash.exe")
        session_name: Session name or None
        session_id: Session GUID
        username: Username
        seq: Optional sequence number (0-999)

    Returns:
        Filename string (without directory)
    """
    if session_name:
        if seq is not None:
            # Named with sequence: .{prefix}{type}_{shell}__{name}--NNN__{guid}_{user}.log
            return f".{prefix}{file_type}_{shell}__{session_name}--{seq:03d}__{session_id}_{username}.log"
        else:
            # Named without sequence: .{prefix}{type}_{shell}__{name}__{guid}_{user}.log
            return f".{prefix}{file_type}_{shell}__{session_name}__{session_id}_{username}.log"
    else:
        # Unnamed: .{prefix}{type}_{shell}_{guid}_{user}.log
        return f".{prefix}{file_type}_{shell}_{session_id}_{username}.log"


def has_sequence_number(filepath: Path) -> bool:
    """Check if a filename already has a sequence number (--NNN)."""
    # Matches --NNN__ pattern (works with or without .log extension)
    return bool(re.search(r"--\d{3}__", filepath.name))


def extract_session_name_from_file(filepath: Path, session_id: str) -> Optional[str]:
    """Extract session name from an existing filename."""
    # Pattern: __{NAME}__{guid} or __{NAME}--NNN__{guid}
    pattern = re.compile(rf"__([^_]+?)(?:--\d{{3}})?__{re.escape(session_id)}")
    match = pattern.search(filepath.name)
    if match:
        return match.group(1)
    return None


def safe_rename(src: Path, dst: Path) -> bool:
    """Safely rename a file with error handling."""
    if src == dst:
        return True  # Already correct name

    if dst.exists():
        debug_log(f"Cannot rename {src.name} to {dst.name}: destination exists")
        return False

    try:
        src.rename(dst)
        debug_log(f"Renamed {src.name} to {dst.name}")
        return True
    except Exception as e:
        debug_log(f"Failed to rename {src.name}: {e}")
        return False


def get_effective_session_name(session_id: str, session_name: Optional[str],
                                sesslog_base: Path) -> Optional[str]:
    """Get session name, falling back to name from existing directories or files.

    If the current session has no name but a named directory exists,
    extract the name from that directory to maintain continuity.
    """
    if session_name:
        return session_name

    # Check if any named directories exist for this session
    try:
        for item in sesslog_base.iterdir():
            if session_id in item.name:
                # Check if it's a named directory (has name before __)
                # Pattern: {name}__{guid}_{user} vs __{guid}_{user}
                if item.is_dir() and not item.name.startswith("__"):
                    # Extract name from directory: {name}__{guid}_{user}
                    match = re.match(rf"^(.+)__{re.escape(session_id)}_", item.name)
                    if match:
                        extracted = match.group(1)
                        debug_log(f"Using session name from existing directory: {extracted}")
                        return extracted

                # Also check files (for backward compatibility with flat files)
                if item.is_file() and "__" in item.name:
                    extracted = extract_session_name_from_file(item, session_id)
                    if extracted:
                        debug_log(f"Using session name from existing file: {extracted}")
                        return extracted
    except Exception:
        pass

    return None


def reconcile_single_category(sesslog_dir: Path, session_id: str, session_name: str,
                               shell: str, username: str, prefix: str,
                               file_type: str) -> Optional[Path]:
    """Reconcile files for a single category and return the target path.

    Returns the path to write to (the "current" file).
    """
    files = find_session_files(sesslog_dir, session_id, prefix, file_type)

    # Build target filename (what the current file should be named)
    target_name = build_filename(prefix, file_type, shell, session_name,
                                  session_id, username, seq=None)
    target_path = sesslog_dir / target_name

    if not files:
        # No existing files - just return target path
        return target_path

    if len(files) == 1:
        only_file = files[0]
        if only_file.name == target_name:
            # Already correctly named
            return target_path
        else:
            # Rename to correct name
            safe_rename(only_file, target_path)
            return target_path

    # Multiple files exist - need sequencing
    # Sort by mtime (oldest first)
    files_sorted = sorted(files, key=lambda f: f.stat().st_mtime)

    # Current = most recent (last in sorted list)
    current_file = files_sorted[-1]
    older_files = files_sorted[:-1]

    # Find highest existing sequence number
    max_seq = find_max_sequence(sesslog_dir, prefix, file_type, shell,
                                 session_name, session_id, username)

    # Rename current file to target (no sequence) if needed
    if current_file.name != target_name:
        if target_path.exists() and target_path != current_file:
            # Target exists but isn't current - this shouldn't happen often
            # Assign sequence to current file instead
            next_seq = max_seq + 1
            seq_name = build_filename(prefix, file_type, shell, session_name,
                                       session_id, username, seq=next_seq)
            safe_rename(current_file, sesslog_dir / seq_name)
            max_seq = next_seq
        else:
            safe_rename(current_file, target_path)

    # Rename older files with sequence numbers (if they don't have one)
    next_seq = max_seq + 1
    for old_file in older_files:
        if has_sequence_number(old_file):
            continue  # Already has sequence, skip

        seq_name = build_filename(prefix, file_type, shell, session_name,
                                   session_id, username, seq=next_seq)
        seq_path = sesslog_dir / seq_name
        if safe_rename(old_file, seq_path):
            next_seq += 1

    return target_path


def reconcile_session_files(sesslog_dir: Path, session_id: str, session_name: str,
                            shell: str, username: str) -> dict[str, Path]:
    """Reconcile all session files and return target paths.

    Applies to all file categories: sesslog, shell, tasks (and Python_ variants).

    Returns:
        Dict mapping file_type to target Path for writing
    """
    if not session_name:
        return {}  # Nothing to reconcile without a name

    targets = {}

    # All prefixes and file types
    prefixes = ["", "Python_"]
    file_types = ["sesslog", "shell", "tasks"]

    for prefix in prefixes:
        for file_type in file_types:
            key = f"{prefix}{file_type}"
            target = reconcile_single_category(
                sesslog_dir, session_id, session_name,
                shell, username, prefix, file_type
            )
            if target:
                targets[key] = target

    return targets


# ============================================================================
# Session Markers
# ============================================================================


def count_session_markers(file_path: Path) -> int:
    """Count existing SESSION START markers in file."""
    if not file_path.exists():
        return 0

    count = 0
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if SESSION_MARKER_SIGNATURE in line:
                    count += 1
    except Exception:
        return 0

    return count


def get_run_number(session_id: str, file_path: Path) -> int:
    """Get the next run number for this session.

    Uses cache for performance within a session run,
    falls back to counting markers in file (always authoritative).
    """
    state_dir = Path.home() / ".claude" / "session-states"
    cache_file = state_dir / f"{session_id}.run"

    # Fast path: cache exists
    if cache_file.exists():
        try:
            return int(cache_file.read_text().strip())
        except (ValueError, OSError):
            pass  # Cache corrupted, regenerate

    # Slow path: count markers in file
    marker_count = count_session_markers(file_path)
    run_number = marker_count + 1

    # Cache for this session run
    try:
        cache_file.write_text(str(run_number))
    except OSError:
        pass

    return run_number


def is_new_session_run(session_id: str) -> bool:
    """Check if this is the first tool call of a new session run."""
    state_dir = Path.home() / ".claude" / "session-states"
    flag_file = state_dir / f"{session_id}.started"
    return not flag_file.exists()


def mark_session_started(session_id: str) -> None:
    """Mark that this session run has been started (marker written)."""
    state_dir = Path.home() / ".claude" / "session-states"
    state_dir.mkdir(parents=True, exist_ok=True)
    flag_file = state_dir / f"{session_id}.started"
    try:
        flag_file.write_text(str(datetime.now()))
    except OSError:
        pass


def write_session_marker(
    file_path: Path,
    run_number: int,
    event_time: datetime,
    session_name: Optional[str] = None
) -> None:
    """Write a visual marker indicating a new session run.

    Includes session name to track renames over time.
    """
    timestamp_str = event_time.strftime('%Y-%m-%d %H:%M:%S')
    name_part = session_name if session_name else "(unnamed)"
    marker = f"""

════════════════════════════════════════════════════════════════════════════════
═══ SESSION START  •  {timestamp_str}  •  Run #{run_number}  •  {name_part}
════════════════════════════════════════════════════════════════════════════════

"""
    atomic_append(file_path, marker.strip())


# ============================================================================
# Session Logger
# ============================================================================


class SessionLogger:
    """Main logger class handling all output files."""

    # Prefix removed - Python is now the primary hook
    FILE_PREFIX = ""

    def __init__(self, config: Config, session: SessionContext, event_time: datetime):
        self.config = config
        self.session = session
        self.event_time = event_time
        self.sesslog_base = Path.home() / ".claude" / "sesslogs"
        self.sesslog_base.mkdir(parents=True, exist_ok=True)

        # Get effective session name (from session or existing files/directories)
        self.effective_name = get_effective_session_name(
            session.session_id, session.session_name, self.sesslog_base
        )

        # Build and create session directory
        self.session_dir = self._get_or_create_session_directory()

        # Reconcile files and get target paths (if we have a name)
        self._reconciled = False
        self._target_paths: dict[str, Path] = {}
        if self.effective_name:
            self._reconcile_files()

        # Handle session start marker
        self._maybe_write_session_marker()

    def _get_or_create_session_directory(self) -> Path:
        """Get or create the session directory, handling renames if needed.

        Uses unified reconcile_session_directory() which handles:
        1. Directory exists with correct name → return it
        2. Directory exists with wrong name (unnamed or old name) → rename dir + files
        3. No directory exists → create it
        """
        session_dir, _ = reconcile_session_directory(
            self.sesslog_base,
            self.session.session_id,
            self.effective_name,
            self.session.username
        )
        return session_dir

    def _reconcile_files(self) -> None:
        """Reconcile session files (rename unnamed files, assign sequences)."""
        if self._reconciled:
            return

        # Get username from session
        username = self.session.username

        # Reconcile all file categories within the session directory
        self._target_paths = reconcile_session_files(
            self.session_dir,
            self.session.session_id,
            self.effective_name,
            self.session.shell_type,
            username
        )
        self._reconciled = True

    def _get_file_path(self, file_type: str) -> Path:
        """Get the correct file path for a file type, using reconciled paths if available."""
        key = f"{self.FILE_PREFIX}{file_type}"

        # Use reconciled path if available
        if key in self._target_paths:
            return self._target_paths[key]

        # Fall back to building path from session context (inside session directory)
        if file_type == "shell":
            return self.session_dir / f".{self.FILE_PREFIX}shell_{self.session.get_filename_context()}.log"
        elif file_type == "sesslog":
            return self.session_dir / f".{self.FILE_PREFIX}sesslog_{self.session.get_filename_context()}.log"
        elif file_type == "tasks":
            return self.session_dir / f".{self.FILE_PREFIX}tasks_{self.session.get_task_filename_context()}.log"
        else:
            raise ValueError(f"Unknown file type: {file_type}")

    @property
    def shell_log_path(self) -> Path:
        """Path to shell history file (.shell_*)."""
        return self._get_file_path("shell")

    @property
    def unified_log_path(self) -> Path:
        """Path to unified session log (.sesslog_*)."""
        return self._get_file_path("sesslog")

    @property
    def task_log_path(self) -> Path:
        """Path to task history file (.tasks_*)."""
        return self._get_file_path("tasks")

    def _maybe_write_session_marker(self) -> None:
        """Write session start marker if this is first call of a new run."""
        if not is_new_session_run(self.session.session_id):
            return  # Already wrote marker for this run

        # Get run number by counting existing markers
        run_number = get_run_number(self.session.session_id, self.unified_log_path)

        # Write markers to shell and sesslog (not tasks)
        # Include session name to track renames over time
        write_session_marker(self.shell_log_path, run_number, self.event_time, self.effective_name)
        write_session_marker(self.unified_log_path, run_number, self.event_time, self.effective_name)

        # Mark session as started
        mark_session_started(self.session.session_id)

        debug_log(f"Wrote session marker: Run #{run_number}")

    def log_entry(self, entry: str, tool_category: str, task_content: Optional[str] = None,
                  event_time: Optional[datetime] = None) -> None:
        """Write entry to appropriate log files.

        Args:
            entry: The formatted log entry string
            tool_category: The category of the tool (e.g., "task", "bash")
            task_content: Optional task-specific content for task tools
            event_time: The event timestamp (ensures consistency across channels)
        """
        ts = event_time or datetime.now()

        # Check for time gaps using event_time
        shell_gap = check_time_gap(self.shell_log_path, self.config.datetime_mode, ts)
        unified_gap = check_time_gap(self.unified_log_path, self.config.datetime_mode, ts)

        # Write to shell log
        atomic_append(self.shell_log_path, entry, add_gap=shell_gap)

        # Write to unified log
        atomic_append(self.unified_log_path, entry, add_gap=unified_gap)

        # Write to task log if task tool (use same event_time for consistency)
        if tool_category == "task" and task_content:
            datetime_part = format_datetime(self.config.datetime_mode, ts)
            task_entry = f"{datetime_part}{{{task_content} }}"
            atomic_append(self.task_log_path, task_entry)

    def log_failure(self, failure_entry: str) -> None:
        """Log a failure entry to history files."""
        atomic_append(self.shell_log_path, failure_entry)
        atomic_append(self.unified_log_path, failure_entry)


# ============================================================================
# Failure Detection
# ============================================================================


def detect_and_log_failure(
    tool_info: ToolInfo, config: Config, logger: SessionLogger, event_time: datetime
) -> None:
    """Enhanced failure detection for Bash commands.

    Args:
        tool_info: Information about the tool call
        config: Logger configuration
        logger: The session logger instance
        event_time: The event timestamp (for consistent timestamps with main entry)
    """
    if tool_info.name != "Bash" or not config.failure_capture_enabled:
        return

    # Look for pre-captured command data
    capture_dir = Path.home() / ".claude" / "captures"
    capture_file = None

    if capture_dir.exists():
        # Find most recent capture file for this session (within last 5 minutes)
        import time

        cutoff_time = time.time() - 300  # 5 minutes ago

        for f in capture_dir.glob(f"{tool_info.session_id}-*"):
            if f.stat().st_mtime > cutoff_time:
                capture_file = f
                break

    # Determine command source and details
    bash_command = ""
    command_cwd = ""

    if capture_file and capture_file.exists():
        try:
            with open(capture_file, "r", encoding="utf-8") as f:
                capture_data = json.load(f)
                bash_command = capture_data.get("bash_command", "")
                command_cwd = capture_data.get("cwd", "")
            capture_file.unlink(missing_ok=True)
        except Exception:
            pass
    else:
        bash_command = tool_info.input.get("command", "")
        command_cwd = os.getcwd()

    # Check for failure indicators
    failure_detected = False
    failure_reason = ""
    error_output = ""

    tool_output = os.environ.get("CLAUDE_TOOL_OUTPUT", "")
    if tool_output:
        error_patterns = [
            "command not found",
            "No such file or directory",
            "Permission denied",
            "syntax error",
            "Failed to execute",
            "exit status",
        ]
        for pattern in error_patterns:
            if pattern in tool_output:
                failure_detected = True
                failure_reason = "error detected in output"
                error_output = tool_output
                break

    if failure_detected:
        # Generate failure entry (use same event_time as main entry)
        datetime_part = format_datetime(config.datetime_mode, event_time)

        pwd_part = ""
        if config.pwd_enabled:
            pwd_part = f' ["{command_cwd or os.getcwd()}"]'

        if should_use_action_only(tool_info.name, config):
            failure_content = "Bash"
        elif config.verbosity <= 1:
            failure_content = bash_command
        else:
            failure_content = f"Bash: {bash_command}"

        failure_entry = f"{datetime_part}{{{failure_content} }} [FAILED: {failure_reason}]{pwd_part}"

        # Add error output if enabled
        if config.failure_capture_stderr and error_output:
            lines = error_output.split("\n")[: config.failure_capture_max_lines]
            formatted_error = "\n".join(f"  {line}" for line in lines)
            if formatted_error:
                failure_entry += "\n" + formatted_error

        logger.log_failure(failure_entry)

    # Cleanup old capture files
    if capture_dir.exists():
        import time

        cutoff_time = time.time() - 600  # 10 minutes ago
        for f in capture_dir.glob(f"{tool_info.session_id}-*"):
            try:
                if f.stat().st_mtime < cutoff_time:
                    f.unlink()
            except Exception:
                pass


# ============================================================================
# Main Entry Point
# ============================================================================


def main() -> None:
    """Entry point for Claude Code hook."""
    # Capture event time ONCE at the earliest point - ensures all channels
    # get identical timestamps for the same event
    event_time = datetime.now()

    debug_log("Hook started (Python)")
    debug_log(f"JSON keys will be logged after parse")

    # Read JSON input from stdin (explicitly decode as UTF-8 for Windows compatibility)
    # On Windows, sys.stdin defaults to CP1252, but Claude sends UTF-8
    try:
        raw_input = sys.stdin.buffer.read().decode('utf-8')
        json_input = json.loads(raw_input)
    except json.JSONDecodeError as e:
        debug_log(f"JSON parse error: {e}")
        print('{"continue": true}')
        return

    debug_log(f"JSON_INPUT length: {len(str(json_input))}")
    debug_log(f"JSON keys: {list(json_input.keys())}")

    # Detect hook event type
    hook_event_name = json_input.get("hook_event_name", "PostToolUse")
    debug_log(f"Hook event: {hook_event_name}")

    # Parse tool info
    tool_info = ToolInfo.from_json(json_input)

    # On SessionStart, apply auto-naming from folder if session is unnamed
    # This stores the name in cache BEFORE build_session_context reads it
    auto_name = apply_auto_name_on_session_start(
        session_id=tool_info.session_id,
        transcript_path=tool_info.transcript_path,
        cwd=json_input.get("cwd", ""),
        hook_event_name=hook_event_name
    )
    if auto_name:
        debug_log(f"Auto-named session from folder: {auto_name}")

    # Build session context
    session_context = build_session_context(tool_info)
    context_string = session_context.get_filename_context()

    # Load configuration
    config = load_configuration(context_string)

    # For non-tool hooks (SessionStart, Stop), we still need to update state
    # and potentially trigger session directory reconciliation
    is_tool_hook = hook_event_name in ("PostToolUse", "PreToolUse", "PostToolUseFailure")

    # Create sesslog directory structure (needed for state file)
    sesslog_base = Path.home() / ".claude" / "sesslogs"
    sesslog_base.mkdir(parents=True, exist_ok=True)

    # Get or create session directory
    # This handles renames if session name changed (e.g., after /rename)
    session_dir, _ = reconcile_session_directory(
        sesslog_base,
        tool_info.session_id,
        session_context.session_name,
        session_context.username
    )

    # Write session state file (enables commands like /renameAI to access context)
    write_session_state(
        session_id=tool_info.session_id,
        transcript_path=tool_info.transcript_path,
        cwd=json_input.get("cwd", ""),
        sesslog_dir=session_dir,
        current_name=session_context.session_name,
    )

    # Create transcript symlink in sesslog directory (non-blocking on failure)
    ensure_transcript_symlink(session_dir, tool_info.transcript_path)

    # For non-tool hooks, we're done after updating state
    if not is_tool_hook:
        debug_log(f"Non-tool hook ({hook_event_name}), state updated, exiting")
        print('{"continue": true}')
        return

    # Check if tool should be logged
    if not should_log_tool(tool_info.name, config):
        print('{"continue": true}')
        return

    # Extract command content
    command_content = get_command_content(tool_info)

    # Generate entry (using captured event_time for consistency)
    entry = generate_entry(tool_info, config, command_content, event_time)

    # Get task content if applicable
    tool_category = categorize_tool(tool_info.name)
    task_content = None
    if tool_category == "task":
        task_content = get_task_content(tool_info.name, tool_info.raw_json)

    # Create logger and write entry (pass event_time for channel consistency)
    # SessionLogger handles file reconciliation and session markers on init
    logger = SessionLogger(config, session_context, event_time)
    logger.log_entry(entry, tool_category, task_content, event_time)

    # Check for failures (Bash only, uses same event_time)
    detect_and_log_failure(tool_info, config, logger, event_time)

    debug_log(f"Logged to {logger.shell_log_path}")

    # Return success
    print('{"continue": true}')


if __name__ == "__main__":
    main()
