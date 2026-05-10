"""Atomic append + 30-minute time-gap detection + overflow fallback.

atomic_append writes via temp-file + rename so a crash mid-write leaves
the channel file unchanged; on hard failure, _write_to_overflow stashes
the entry in `<name>.overflow.N` so nothing is silently lost. check_time_gap
compares the most-recent log timestamp against the current event time to
emit a blank line between conversational sessions.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from cclogger.debug import debug_log


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
