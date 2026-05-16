"""Append+lock writes + 30-minute time-gap detection + overflow fallback.

atomic_append uses POSIX `O_APPEND` semantics (Unix) and Windows
cooperative sharing modes (default for Python's `open(path, 'ab')` via
`_SH_DENYNO`) plus an exclusive byte-0 lock from `file_lock` to
coordinate concurrent hook subprocess writers. Reader handles held by
text editors / antivirus / Explorer thumbnailers do NOT block this path
because we never try to rename or truncate the destination — we open
in append mode with shared sharing modes.

Path 1 retry (3 attempts, exponential backoff) handles the rare case
where lock acquisition itself fails. After all retries exhaust, the
overflow fallback (`<name>.overflow.N`) preserves the entry so nothing
is silently lost. With append+lock as the primary path, overflow
should be essentially unreachable under normal use.

migrate_overflow_files absorbs legacy `.overflow.N` files from prior
versions (which used a temp-file+rename primary path that fragmentized
on Windows file-lock conflicts) into the corresponding main log file
on first run after upgrade. Idempotent via the `.overflow_migrated_v0.3.7`
sentinel marker in the session directory.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from cclogger.debug import debug_log
from cclogger.file_lock import lock_exclusive, lock_nonblocking, unlock


# Lock acquisition retry tuning. Three attempts with exponential
# backoff. With append+lock as the primary path these are very
# rarely exercised — they exist as defense-in-depth for the exotic
# case where the lock itself can't be acquired (e.g., another hook
# subprocess holds it for an unusually long write).
LOCK_RETRY_ATTEMPTS = 3
LOCK_RETRY_BACKOFF_MS = (10, 50, 200)

# One-time migration sentinel. Presence in a session directory means
# legacy `.overflow.N` files have already been absorbed (or there were
# none to absorb). v0.3.7-pre rename: was `.overflow_migrated_v0.3.7`.
# The old name is still recognized on read so existing sentinels keep
# working (see _has_overflow_sentinel below).
OVERFLOW_MIGRATION_SENTINEL = ".session-logger-overflow-migrated"
_LEGACY_OVERFLOW_SENTINELS = (".overflow_migrated_v0.3.7",)

# One-time orphan-name sweep sentinel. Presence means the directory has
# already been scanned for log files bearing OLD session names (Bug B
# pre-v0.3.7-pre). Renamed from `.orphan_session_name_swept_v0.3.7`.
ORPHAN_SWEEP_SENTINEL = ".session-logger-orphans-swept"
_LEGACY_ORPHAN_SENTINELS = (".orphan_session_name_swept_v0.3.7",)

# Per-session-dir README that explains the .session-logger-* state files.
# Written exactly once, only if no file already exists at that name --
# users sometimes drop their own README.md in session dirs, and we never
# overwrite. The README.session-logger.md suffix makes ownership obvious.
SESSION_LOGGER_README = "README.session-logger.md"


# ============================================================================
# Time gap detection
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


# ============================================================================
# Append+lock write primitive
# ============================================================================


def _safe_append_bytes(file_path: Path, payload_bytes: bytes) -> None:
    """Open in append mode, lock, write+fsync, unlock, close.

    Single-attempt path used by both `atomic_append` (which adds retry
    + overflow fallback on top) and `migrate_overflow_files` (which
    wants the raw primitive without recursion into overflow fallback).

    Raises whatever the underlying open/lock/write raises.
    """
    with open(file_path, "ab") as fp:
        lock_exclusive(fp)
        try:
            fp.write(payload_bytes)
            fp.flush()
            os.fsync(fp.fileno())
        finally:
            unlock(fp)


def atomic_append(file_path: Path, content: str, add_gap: bool = False) -> None:
    """Append content to file using append+lock primitive with retry.

    Primary path: open(path, 'ab') with cooperative sharing modes
    (default on both POSIX and Windows) + exclusive byte-0 lock via
    file_lock. Survives concurrent reader handles from text editors,
    antivirus, and Explorer.

    On lock acquisition failure: retry with exponential backoff up to
    LOCK_RETRY_ATTEMPTS times. After exhaustion, fall back to
    `_write_to_overflow` so the entry is preserved rather than dropped.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Strip null bytes that could corrupt log file or confuse readers
    content = content.replace("\x00", "")

    # Build the bytes to write in one shot so the locked region stays small
    payload = ""
    if add_gap:
        payload += "\n"
    payload += content + "\n"
    payload_bytes = payload.encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(LOCK_RETRY_ATTEMPTS):
        try:
            _safe_append_bytes(file_path, payload_bytes)
            return  # Success
        except Exception as e:
            last_error = e
            if attempt < LOCK_RETRY_ATTEMPTS - 1:
                time.sleep(LOCK_RETRY_BACKOFF_MS[attempt] / 1000.0)
            continue

    # All retries exhausted — preserve the entry in an overflow file so
    # the next migration pass (or manual recovery) can absorb it.
    debug_log(
        f"Append to {file_path.name} failed after {LOCK_RETRY_ATTEMPTS} "
        f"attempts: {last_error}. Writing to overflow."
    )
    _write_to_overflow(file_path, content, add_gap)


def _write_to_overflow(file_path: Path, content: str, add_gap: bool) -> None:
    """Write entry to overflow file when append+lock fails.

    Uses incrementing suffix: .overflow.1, .overflow.2, etc.
    Plain append (no lock — overflow files are write-once from the
    point of any single hook invocation; concurrent hooks would each
    pick a fresh suffix). Isolated from main file by name so the main
    log stays uncorrupted.

    Should be essentially unreachable with append+lock as the primary
    path. Migration absorbs any legacy overflows on next session start.
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
# One-time overflow migration
# ============================================================================


_OVERFLOW_PATTERN = re.compile(r"^(.+)\.overflow\.\d+$")


def migrate_overflow_files(session_dir: Path) -> int:
    """One-time migration of legacy `.overflow.N` files into main log files.

    Idempotent via `OVERFLOW_MIGRATION_SENTINEL` marker in the session
    directory. Safe to call on every SessionStart — does nothing if
    the sentinel is present.

    For each main log file with one or more `.overflow.N` siblings:
      1. Sort overflows by mtime (preserves original write order)
      2. Append a banner + concatenated overflow contents to the main file
      3. Delete the overflow files
    Then drops the sentinel marker.

    Returns: number of overflow files absorbed (0 if migration already
    ran, no overflow files present, or session_dir doesn't exist yet).
    """
    if not session_dir.exists():
        return 0

    sentinel = session_dir / OVERFLOW_MIGRATION_SENTINEL
    if sentinel.exists():
        return 0
    # Recognize legacy sentinel names so existing dirs don't re-scan after the
    # v0.3.7-pre rename. Drop the new-named sentinel alongside so future
    # checks find the new name immediately.
    for legacy_name in _LEGACY_OVERFLOW_SENTINELS:
        if (session_dir / legacy_name).exists():
            _drop_sentinel(sentinel, absorbed=0, kind="overflow")
            _ensure_session_logger_readme(session_dir)
            return 0

    # Find all .overflow.N files in session dir
    overflow_files: list[tuple[Path, str]] = []
    try:
        for child in session_dir.iterdir():
            if not child.is_file():
                continue
            match = _OVERFLOW_PATTERN.match(child.name)
            if match:
                overflow_files.append((child, match.group(1)))
    except OSError as e:
        debug_log(f"Could not scan {session_dir} for overflow files: {e}")
        return 0

    if not overflow_files:
        # Drop sentinel anyway so subsequent SessionStarts don't re-scan
        _drop_sentinel(sentinel, absorbed=0, kind="overflow")
        _ensure_session_logger_readme(session_dir)
        return 0

    # Sort by mtime to preserve write order across the session
    overflow_files.sort(key=lambda item: item[0].stat().st_mtime)

    # Group by base file name
    by_base: dict[str, list[Path]] = {}
    for overflow_path, base_name in overflow_files:
        by_base.setdefault(base_name, []).append(overflow_path)

    absorbed_count = 0
    migration_ts = datetime.now()
    for base_name, paths in by_base.items():
        main_path = session_dir / base_name
        # Build the migration block: single banner + all overflow contents
        ts_str = migration_ts.strftime("%Y-%m-%d %H:%M:%S")
        banner = (
            f"\n═══ MIGRATED FROM OVERFLOW: {len(paths)} file(s) "
            f"absorbed at {ts_str} ═══\n\n"
        )
        merged = banner.encode("utf-8")
        for overflow_path in paths:
            try:
                merged += overflow_path.read_bytes()
            except Exception as e:
                debug_log(
                    f"Failed to read overflow {overflow_path.name}: {e}"
                )
                continue
            # Ensure trailing newline between concatenated overflow files
            if not merged.endswith(b"\n"):
                merged += b"\n"

        # Use the safe append primitive directly (no retry/overflow fallback —
        # if migration itself fails we want the original .overflow.N files
        # to stay put for a future attempt rather than silently doubling them).
        try:
            _safe_append_bytes(main_path, merged)
        except Exception as e:
            debug_log(
                f"Failed to migrate overflow into {main_path.name}: {e}. "
                f"Leaving overflow files in place for retry."
            )
            continue

        # Delete absorbed overflow files. If a delete fails (e.g., still
        # locked), leave it — next migration attempt will re-absorb +
        # re-delete; minor duplication is preferable to data loss.
        for overflow_path in paths:
            try:
                overflow_path.unlink()
                absorbed_count += 1
            except OSError as e:
                debug_log(
                    f"Failed to delete overflow {overflow_path.name}: {e}"
                )

    _drop_sentinel(sentinel, absorbed=absorbed_count, kind="overflow")
    _ensure_session_logger_readme(session_dir)
    debug_log(
        f"Overflow migration complete in {session_dir.name}: "
        f"{absorbed_count} file(s) absorbed"
    )
    return absorbed_count


_SENTINEL_BODIES = {
    "overflow": (
        "# claude-session-logger overflow migration marker\n"
        "#\n"
        "# This file's presence tells the hook that any legacy `.overflow.N`\n"
        "# files in this directory have already been absorbed into the\n"
        "# corresponding main `.<channel>_*.log` file. Pre-v0.3.7 versions\n"
        "# of atomic_append occasionally fell back to `.overflow.N` siblings\n"
        "# on Windows file-lock conflicts; v0.3.7's append+lock primitive\n"
        "# eliminated that failure mode.\n"
        "#\n"
        "# Safe to delete: yes. Deletion causes the scan to re-run on next\n"
        "# SessionStart; if no `.overflow.N` files are present (the normal\n"
        "# state since v0.3.7), the scan is a no-op and this marker\n"
        "# regenerates automatically.\n"
        "#\n"
        "# See README.session-logger.md (same directory) for an overview.\n"
    ),
    "orphan": (
        "# claude-session-logger orphan-name sweep marker\n"
        "#\n"
        "# This file's presence tells the hook that any log files bearing an\n"
        "# OLD session name (left behind by a pre-v0.3.7-pre rename bug,\n"
        "# Github #49) have already been moved to `baks/` in this directory.\n"
        "# Going forward, rename reconciliation enumerates every declared\n"
        "# channel + every subtype derivative, so new orphans should not form.\n"
        "#\n"
        "# Safe to delete: yes. Deletion causes the sweep to re-run on next\n"
        "# SessionStart; in the normal state (no orphans present) the scan\n"
        "# is a no-op and this marker regenerates automatically.\n"
        "#\n"
        "# See README.session-logger.md (same directory) for an overview.\n"
    ),
}


def _drop_sentinel(sentinel: Path, absorbed: int, kind: str = "overflow") -> None:
    """Write the migration sentinel marker with self-documenting content.

    Body explains what the marker means and confirms the file is safe to
    delete. Best-effort: logs and continues on write failure.
    """
    body = _SENTINEL_BODIES.get(kind, _SENTINEL_BODIES["overflow"])
    timestamp = datetime.now().isoformat()
    content = f"# Created {timestamp} | absorbed={absorbed}\n{body}"
    try:
        sentinel.write_text(content, encoding="utf-8")
    except OSError as e:
        debug_log(f"Could not drop {kind} sentinel {sentinel.name}: {e}")


_SESSION_LOGGER_README_BODY = """# claude-session-logger session directory

This directory holds log files produced by the
[claude-session-logger](https://github.com/DazzleML/claude-session-logger)
hook for one Claude Code session. The contents are managed by the hook;
this README is a one-time drop explaining the housekeeping markers you
may notice here.

## File types you may see

| File pattern | What it is |
|---|---|
| `.<channel>_*.log` | Active log files (`.shell_*`, `.sesslog_*`, `.convo_*`, `.tools_*`, `.agents_*`, `.unknowns_*`, `.tasks_*`, `.fileio_*`) |
| `.<channel>-<subtype>_*.log` | Per-subtype split files for channels that opt in via `ChannelOptions.subtype_split` (the `agents` channel defaults true so `.agents-help_*` etc. appear automatically) |
| `transcript.jsonl` (symlink) | Shortcut to Claude Code's full transcript for this session |
| `baks/` | Recoverable backup of files moved by housekeeping (see below) |
| `.session-logger-overflow-migrated` | Marker: legacy `.overflow.N` files (if any) have been absorbed into their main log files |
| `.session-logger-orphans-swept` | Marker: log files bearing OLD session names (from a pre-v0.3.7-pre rename bug) have been moved to `baks/` |

## Are the `.session-logger-*` markers safe to delete?

Yes. They're state files: presence tells the hook "we already did this cleanup, skip the scan." Deleting one just causes the corresponding scan to re-run on the next SessionStart, which is a no-op when there's nothing to clean up.

## Is `baks/` safe to delete?

The hook never reads from `baks/` once a file lands there. It exists for your peace of mind: if a sweep moved something you wanted to keep, you can recover it. Safe to delete the whole subdirectory once you've reviewed it.

## Where does configuration live?

User config: `~/.claude/plugins/settings/session-logger.json`
Schema: see the [project repository](https://github.com/DazzleML/claude-session-logger) for `hooks/schemas/session-logger.schema.json`.
"""


def _ensure_session_logger_readme(session_dir: Path) -> None:
    """Drop README.session-logger.md in `session_dir` if it doesn't exist.

    NEVER overwrites an existing file at that path -- the user may have
    their own README in the directory. Best-effort: logs and continues on
    write failure.

    Naming: `README.session-logger.md` (not `README.md`) avoids any
    collision with a user-placed README and makes ownership unambiguous.
    """
    readme = session_dir / SESSION_LOGGER_README
    if readme.exists():
        return  # never overwrite
    try:
        readme.write_text(_SESSION_LOGGER_README_BODY, encoding="utf-8")
    except OSError as e:
        debug_log(f"Could not write session-logger README in {session_dir.name}: {e}")


# ============================================================================
# One-time orphan-session-name sweep (Bug B cleanup, v0.3.7-pre)
# ============================================================================


def _embedded_session_name(filename: str, session_id: str) -> Optional[str]:
    """Extract the session name embedded in a log filename, or None.

    Pattern: `.{channel}_{shell-bits}__{name}__{guid}_{user}[.log]`.
    Files without an embedded name (unnamed-form) or that don't embed the
    GUID return None. Used by the sweep to identify orphans whose embedded
    name doesn't match the current session name.
    """
    escaped_id = re.escape(session_id)
    pattern = re.compile(rf"^\.[\w-]+_[\w.]+__([^_]+?)(?:--\d{{3}})?__{escaped_id}_\w+(\.log)?$")
    match = pattern.match(filename)
    if match:
        return match.group(1)
    return None


def sweep_orphan_session_name_files(
    session_dir: Path, current_session_name: str, session_id: str
) -> int:
    """Move files with current session UUID but wrong session name to baks/.

    v0.3.7-pre (Bug B cleanup): when reconcile_session_files was hardcoded
    to ["sesslog", "shell", "tasks"], any other channel file (.tools_*,
    .convo_*, .agents_*, etc.) AND any subtype derivative kept getting
    re-created under the OLD session name on every hook event after a
    session rename. Result: duplicated per-channel files with different
    embedded names. This sweep moves orphans (embedded name != current)
    into `<session_dir>/baks/` for recoverable cleanup.

    Idempotent via sentinel (mirrors migrate_overflow_files pattern).
    Called from SessionLogger.__init__ AFTER `_reconcile_files()` (so
    canonical-name renames are done first) and AFTER `migrate_overflow_files`
    (so overflows are absorbed first). Anything still bearing the wrong
    session name at this point is an actual orphan -- something the renamer
    couldn't handle (e.g., destination already existed).

    Returns: number of orphan files moved to baks/ (0 if sweep already
    ran or no orphans present). Drops sentinel even on zero moves.
    """
    if not session_dir.exists() or not current_session_name:
        return 0
    sentinel = session_dir / ORPHAN_SWEEP_SENTINEL
    if sentinel.exists():
        return 0
    # Recognize legacy sentinel names so existing dirs don't re-scan after
    # the v0.3.7-pre rename. Drop the new-named sentinel alongside.
    for legacy_name in _LEGACY_ORPHAN_SENTINELS:
        if (session_dir / legacy_name).exists():
            _drop_sentinel(sentinel, absorbed=0, kind="orphan")
            _ensure_session_logger_readme(session_dir)
            return 0

    baks_dir: Optional[Path] = None  # Created on first move
    moved = 0
    try:
        for f in session_dir.iterdir():
            if not f.is_file():
                continue
            embedded = _embedded_session_name(f.name, session_id)
            if embedded is None or embedded == current_session_name:
                continue  # No embedded name OR canonical -- not an orphan
            # Move to baks/<filename>; numeric suffix on collision.
            if baks_dir is None:
                baks_dir = session_dir / "baks"
                try:
                    baks_dir.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    debug_log(f"Could not create baks dir for sweep: {e}")
                    break
            dest = baks_dir / f.name
            i = 1
            while dest.exists():
                dest = baks_dir / f"{f.name}.{i}"
                i += 1
            try:
                f.rename(dest)
                moved += 1
                debug_log(f"Swept orphan {f.name} -> baks/{dest.name}")
            except OSError as e:
                debug_log(f"Could not sweep orphan {f.name}: {e}")
    except OSError as e:
        debug_log(f"Sweep scan of {session_dir.name} failed: {e}")

    # Drop sentinel even on zero moves so subsequent SessionStarts skip the scan
    _drop_sentinel(sentinel, absorbed=moved, kind="orphan")
    _ensure_session_logger_readme(session_dir)

    if moved:
        debug_log(
            f"Orphan-name sweep complete in {session_dir.name}: {moved} file(s) moved to baks/"
        )
    return moved
