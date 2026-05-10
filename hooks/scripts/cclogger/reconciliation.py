"""Retroactive directory + filename reconciliation when a session is renamed.

Handles three transitions:
  - Unnamed → Named (auto-name applied on SessionStart, or user issued /rename)
  - Named → Renamed (user changed the title mid-session)
  - Multiple files for the same session (assigns --NNN sequence numbers)

build_session_directory and build_filename are the canonical name producers;
the rest of the module finds existing log files for a session GUID and
relocates them to match the current expected name.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from cclogger.debug import debug_log
from cclogger.session_naming import sanitize_dirname


# ============================================================================
# Session Directory Management
# ============================================================================


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
    """Rename log files in directory to reflect new session name.

    Handles both unnamed->named and named->renamed transitions.
    This is the file-level counterpart to directory renaming.

    Only renames files matching the log filename pattern (.sesslog_*,
    .shell_*, .tasks_*). Other files (transcript.jsonl, etc.) are
    skipped to prevent corruption from substring replacement (#17).
    """
    if not directory.exists():
        return

    # Only rename our log files -- skip transcript.jsonl and anything else
    log_prefixes = (".sesslog_", ".shell_", ".tasks_")

    for f in directory.iterdir():
        if not f.is_file():
            continue

        old_name = f.name

        # Skip files that aren't our log files
        if not old_name.startswith(log_prefixes):
            continue

        new_name = None

        if old_session_name:
            # Named -> Renamed: use targeted regex to replace session name
            # only in its structural position (between __ delimiters before GUID)
            # Pattern: .prefix_shell__{old_name}__{guid}_{user}...
            escaped_old = re.escape(old_session_name)
            escaped_id = re.escape(session_id)
            pattern = rf"(?<=__){escaped_old}(?=__{escaped_id})"
            if re.search(pattern, old_name):
                new_name = re.sub(pattern, new_session_name, old_name)
        else:
            # Unnamed -> Named: insert name before GUID
            # Pattern: .type_shell_{guid}_{user}[.log] -> .type_shell__{name}__{guid}_{user}[.log]
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
    # Filesystem limit is 255 chars; compute budget for the name portion
    # Suffix is: __{session_id}_{username}  (2 + len(id) + 1 + len(user))
    suffix_len = 2 + len(session_id) + 1 + len(username)
    max_name_len = max(255 - suffix_len, 20)  # floor of 20 to keep something readable

    if session_name:
        safe_name = sanitize_dirname(session_name, max_len=max_name_len)
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
