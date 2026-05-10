"""Session-name discovery + auto-derivation from cwd + filesystem sanitization.

get_session_name reads the user-given title from the transcript or the
sessions-index.json fallback; derive_session_name_from_cwd auto-generates
a sensible name when no custom title exists; apply_auto_name_on_session_start
wires the auto-name into the name-cache on SessionStart; sanitize_dirname
makes any name safe for filesystem use.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from dazzle_filekit import normalize_cross_platform_path

from cclogger.debug import debug_log


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


def sanitize_dirname(name: str, max_len: int = 200) -> str:
    """Sanitize session name for filesystem safety.

    Args:
        name: The session name to sanitize
        max_len: Maximum length for the name portion (default 200,
                 callers should compute based on filesystem limit
                 minus suffix overhead)

    Returns:
        Filesystem-safe version of the name
    """
    # Replace characters that are problematic on Windows/Unix filesystems
    safe = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Also replace any control characters
    safe = re.sub(r'[\x00-\x1f]', '_', safe)
    # Truncate to max length
    return safe[:max_len]
