"""Session-start + context-compaction visual markers, plus run-number counting.

The two header-rule markers (`═══ SESSION START` and `═══ CONTEXT COMPACTED`)
are appended to the unified sesslog channel; their line counts authoritatively
provide the Run # and Compaction # values displayed in subsequent markers.
get_run_number caches the result per session in `~/.claude/session-states/`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from cclogger.file_io import atomic_append


# Session marker signatures - used to count run/compaction numbers
SESSION_MARKER_SIGNATURE = "═══ SESSION START"
COMPACTION_MARKER_SIGNATURE = "═══ CONTEXT COMPACTED"


# ============================================================================
# Session Markers
# ============================================================================


def count_session_markers(file_path: Path) -> int:
    """Count existing SESSION START markers in file (excludes compaction markers)."""
    return _count_markers(file_path, SESSION_MARKER_SIGNATURE)


def count_compaction_markers(file_path: Path) -> int:
    """Count existing CONTEXT COMPACTED markers in file."""
    return _count_markers(file_path, COMPACTION_MARKER_SIGNATURE)


def _count_markers(file_path: Path, signature: str) -> int:
    """Count markers matching a specific signature in a log file."""
    if not file_path.exists():
        return 0

    count = 0
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if signature in line:
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
    marker_number: int,
    event_time: datetime,
    session_name: Optional[str] = None,
    source: Optional[str] = None
) -> None:
    """Write a visual marker indicating a new session run or context compaction.

    Args:
        file_path: Path to log file
        marker_number: Run # for session starts, Compaction # for compactions
        event_time: Timestamp for the marker
        session_name: Session name to display
        source: Source of the event ('compact' for context compaction, else session start)
    """
    timestamp_str = event_time.strftime('%Y-%m-%d %H:%M:%S')
    name_part = session_name if session_name else "(unnamed)"

    # Determine marker type and counter label based on source (#14)
    if source == "compact":
        marker_type = "CONTEXT COMPACTED"
        counter_label = f"Compaction #{marker_number}"
    else:
        marker_type = "SESSION START"
        counter_label = f"Run #{marker_number}"

    marker = f"""

════════════════════════════════════════════════════════════════════════════════
═══ {marker_type}  •  {timestamp_str}  •  {counter_label}  •  {name_part}
════════════════════════════════════════════════════════════════════════════════

"""
    atomic_append(file_path, marker.strip())
