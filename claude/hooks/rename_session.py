#!/usr/bin/env python3
"""Rename a Claude Code session.

Usage: python rename_session.py <session_id> <new_name>

This script:
1. Reads session state from ~/.claude/session-states/{session_id}.json
2. Creates timestamped backup of sessions-index.json
3. Updates sessions-index.json with new customTitle
4. Appends custom-title entry to transcript .jsonl
5. The hook system will rename the folder on next invocation
"""

import json
import sys
import re
from datetime import datetime, timezone
from pathlib import Path

# Import dazzle-filekit for cross-platform operations
try:
    from dazzle_filekit import copy_file, normalize_cross_platform_path
    HAS_FILEKIT = True
except ImportError:
    HAS_FILEKIT = False
    import shutil


def sanitize_session_name(name: str, max_words: int = 10) -> str:
    """Convert name to file-safe format.

    Rules:
    - Lowercase
    - Spaces → underscores
    - Special chars → removed or dashes
    - Collapse multiple separators
    - Max word limit

    Examples:
    - "Fix Auth Bug" → "fix_auth_bug"
    - "Claude Code: Bash History" → "claude-code_bash_history"
    """
    # Lowercase
    name = name.lower()

    # Replace colons/slashes with dashes (same-concept separator)
    name = re.sub(r'[:/\\]', '-', name)

    # Replace spaces with underscores (word separator)
    name = re.sub(r'\s+', '_', name)

    # Remove unsafe characters, keep alphanumeric, dash, underscore
    name = re.sub(r'[^a-z0-9_-]', '', name)

    # Collapse multiple separators
    name = re.sub(r'[-_]{2,}', '_', name)

    # Trim leading/trailing separators
    name = name.strip('-_')

    # Limit words (split on underscore, take first N, rejoin)
    words = name.split('_')
    if len(words) > max_words:
        words = words[:max_words]
    name = '_'.join(words)

    return name


def normalize_path(path_str: str) -> Path:
    """Normalize path for cross-platform compatibility."""
    if HAS_FILEKIT:
        return normalize_cross_platform_path(path_str)
    return Path(path_str)


def create_backup(file_path: Path) -> Path:
    """Create timestamped backup of a file using system-level copy.

    Uses dazzle-filekit's copy_file() which preserves permissions via
    robocopy on Windows and shutil.copy2 on Unix.

    Returns the backup path.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
    backup_path = file_path.with_suffix(f".json.{timestamp}.bak")

    if file_path.exists():
        if HAS_FILEKIT:
            # Use dazzle-filekit for system-level copy with attribute preservation
            success = copy_file(file_path, backup_path, preserve_attrs=True, overwrite=False)
            if success:
                print(f"Created backup: {backup_path.name}")
            else:
                print(f"Warning: Backup creation failed, falling back to text copy")
                backup_path.write_text(file_path.read_text(encoding='utf-8'), encoding='utf-8')
                print(f"Created backup (text): {backup_path.name}")
        else:
            # Fallback: use shutil.copy2 which preserves metadata
            shutil.copy2(file_path, backup_path)
            print(f"Created backup: {backup_path.name}")

    return backup_path


def update_sessions_index(sessions_index_path: Path, session_id: str, new_name: str) -> bool:
    """Update the customTitle in sessions-index.json.

    Returns True if successful, False otherwise.
    """
    if not sessions_index_path.exists():
        print(f"Error: sessions-index.json not found at {sessions_index_path}")
        return False

    try:
        data = json.loads(sessions_index_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        print(f"Error parsing sessions-index.json: {e}")
        return False

    # Find and update the session entry
    entries = data.get("entries", [])
    found = False
    for entry in entries:
        if entry.get("sessionId") == session_id:
            entry["customTitle"] = new_name
            found = True
            break

    if not found:
        print(f"Warning: Session {session_id} not found in sessions-index.json")
        print("The session may be too new. Proceeding with transcript update only.")
        return True  # Not fatal - transcript update may still work

    # Write back
    sessions_index_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(f"Updated sessions-index.json: customTitle = {new_name}")
    return True


def update_transcript(transcript_path: Path, new_name: str) -> bool:
    """Append custom-title entry to transcript .jsonl.

    Returns True if successful, False otherwise.
    """
    if not transcript_path.exists():
        print(f"Error: Transcript not found at {transcript_path}")
        return False

    entry = {
        "type": "custom-title",
        "customTitle": new_name,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }

    try:
        with open(transcript_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
        print(f"Appended custom-title to transcript: {new_name}")
        return True
    except Exception as e:
        print(f"Error writing to transcript: {e}")
        return False


def clear_session_caches(session_id: str) -> None:
    """Clear session name caches so hook picks up the new name.

    Clears caches in both the legacy /tmp location and the new
    ~/.claude/session-states/ location for compatibility.
    """
    cache_locations = [
        # Legacy location (will be migrated in log-command.py)
        Path(f"/tmp/claude-session-name-{session_id}"),
        # New location within session-states
        Path.home() / ".claude" / "session-states" / f"{session_id}.name-cache",
    ]

    for cache_file in cache_locations:
        if cache_file.exists():
            try:
                cache_file.unlink()
                print(f"Cleared cache: {cache_file.name}")
            except Exception as e:
                print(f"Warning: Could not clear {cache_file.name}: {e}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python rename_session.py <session_id> <new_name>")
        print("Example: python rename_session.py abc123-def456 fix_auth_bug")
        sys.exit(1)

    session_id = sys.argv[1]
    raw_name = " ".join(sys.argv[2:])  # Handle multi-word names
    new_name = sanitize_session_name(raw_name)

    print(f"Session ID: {session_id}")
    print(f"New name (raw): {raw_name}")
    print(f"New name (sanitized): {new_name}")
    if HAS_FILEKIT:
        print(f"Using dazzle-filekit for cross-platform operations")
    print()

    # Read session state
    state_file = Path.home() / ".claude" / "session-states" / f"{session_id}.json"
    if not state_file.exists():
        print(f"Error: Session state file not found: {state_file}")
        print("Make sure the hook has run at least once for this session.")
        sys.exit(1)

    try:
        state = json.loads(state_file.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        print(f"Error parsing session state: {e}")
        sys.exit(1)

    # Normalize paths from state file (handles /c/Users/... style paths)
    sessions_index_path = normalize_path(state.get("sessions_index_path", ""))
    transcript_path = normalize_path(state.get("transcript_path", ""))

    print(f"Sessions index: {sessions_index_path}")
    print(f"Transcript: {transcript_path}")
    print()

    # Create backup of sessions-index.json
    if sessions_index_path.exists():
        create_backup(sessions_index_path)

    # Update sessions-index.json
    index_ok = update_sessions_index(sessions_index_path, session_id, new_name)

    # Update transcript
    transcript_ok = update_transcript(transcript_path, new_name)

    # Clear session name caches
    clear_session_caches(session_id)

    print()
    if index_ok and transcript_ok:
        print(f"[OK] Session renamed to: {new_name}")
        print("  The sesslog folder will rename on the next hook trigger (any tool use).")
    elif transcript_ok:
        print(f"[PARTIAL] Transcript updated, but sessions-index.json may need manual update.")
    else:
        print("[FAILED] Rename failed. Check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
