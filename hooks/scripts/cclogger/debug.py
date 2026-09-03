"""Debug logging + dazzle-filekit auto-install + unknown-tool warning throttle.

Foundation module — depends only on stdlib + cclogger.paths (itself
stdlib-only, so no import cycle even though __init__ loads debug first).
Other cclogger modules import debug_log from here. _ensure_dazzle_filekit()
is invoked once by
cclogger/__init__.py so that downstream modules can `from dazzle_filekit
import ...` without each one bootstrapping the install.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from cclogger import paths


def _ensure_dazzle_filekit():
    """Auto-install dazzle-filekit if missing (e.g. running inside a venv)."""
    try:
        import dazzle_filekit  # noqa: F401
        return
    except ImportError:
        pass

    # Avoid retrying on every hook call if install previously failed
    sentinel = paths.logs() / ".dazzle_filekit_install_failed"
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


# Debug logging - persistent location under the (possibly relocated) Claude dir
DEBUG_LOG = paths.logs() / "hook-debug.log"

# Throttle directory for "unknown tool encountered" warnings. Each unknown
# tool name gets a sentinel file on first sighting; subsequent invocations
# (across hook subprocesses, not just within one process) skip the warning.
# Delete the directory or individual sentinels to re-trigger warnings.
UNKNOWN_TOOL_WARN_DIR = paths.logs() / ".unknown_tool_warnings"
# Phase 2+3 Step 10: parallel sentinel directory for unknown role names.
# When a LogEntry's role is not in the closed ROLES enum, formatters render
# it as `??:<role>` (visible in logs) AND emit a one-time debug-log warning
# via this helper. Sibling directory keeps the unknown-tool and unknown-role
# warning streams independent.
UNKNOWN_ROLE_WARN_DIR = paths.logs() / ".unknown_role_warnings"


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


UNKNOWN_COLLECT_KEY_WARN_DIR = UNKNOWN_ROLE_WARN_DIR.parent / ".unknown_collect_key_warnings"


def _warn_unknown_collect_key_once(key: str) -> None:
    """One-time warning for a ChannelOptions.collect key this version
    doesn't recognize (#53). Sibling sentinel dir, same pattern as the
    unknown-tool/role warnings. Unknown keys are IGNORED (not errors) so
    configs written for newer plugin versions degrade gracefully here.

    Best-effort -- silent on errors so the hook itself never breaks.
    """
    try:
        UNKNOWN_COLLECT_KEY_WARN_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_\-.]", "_", key)
        sentinel = UNKNOWN_COLLECT_KEY_WARN_DIR / f"{safe_name}.warned"
        try:
            sentinel.open("x").close()
        except FileExistsError:
            return
        debug_log(
            f"Unknown collect key '{key}' in channel options - ignored. "
            f"Recognized keys this version: see COLLECT_RECOGNIZED_KEYS in "
            f"cclogger/models.py (config may be from a newer plugin version)"
        )
    except Exception:
        pass


UNKNOWN_EXCLUDE_KEY_WARN_DIR = UNKNOWN_ROLE_WARN_DIR.parent / ".unknown_exclude_key_warnings"


def _warn_unknown_exclude_key_once(key: str) -> None:
    """One-time warning for a ChannelOptions.exclude key this version doesn't
    recognize (the subtractive mirror of collect, 2026-09-02). Same sentinel
    pattern and the same rule: unknown keys are IGNORED so configs written
    for newer plugin versions degrade gracefully. Best-effort, never raises.
    """
    try:
        UNKNOWN_EXCLUDE_KEY_WARN_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_\-.]", "_", key)
        sentinel = UNKNOWN_EXCLUDE_KEY_WARN_DIR / f"{safe_name}.warned"
        try:
            sentinel.open("x").close()
        except FileExistsError:
            return
        debug_log(
            f"Unknown exclude key '{key}' in channel options - ignored. "
            f"Recognized keys this version: see EXCLUDE_RECOGNIZED_KEYS in "
            f"cclogger/models.py (config may be from a newer plugin version)"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Hook self-observability (2026-09-02 incident, v0.3.16)
# ---------------------------------------------------------------------------
#
# The hook cannot observe its own kill (Claude Code's hook timeout), and
# before the incident a 5-60s cost per event was invisible until a user saw
# "hook timed out". Three cheap instruments: (1) a per-invocation timer that
# writes ONE line to session-logger-perf.log when an invocation is slow, with
# a phase breakdown; (2) an in-flight marker per invocation -- a stale one
# found by a later invocation proves the earlier one never finished; (3) a
# once-per-session warning when a directory grows an unusual number of
# derived channel basenames (the shape of the incident). Observability only:
# nothing here changes routing or drops an entry.

import os
import time
from pathlib import Path
from typing import Optional

PERF_LOG_NAME = "session-logger-perf.log"
SLOW_HOOK_SECONDS = 1.0
STALE_INFLIGHT_SECONDS = 120.0
DERIVED_CHANNEL_WARN_THRESHOLD = 64
# Test override only. None -> resolved at CALL time (see derived_growth_warn_dir),
# so a relocated CLAUDE_DIR or an isolated test home is honored -- an
# import-time path here leaked test sentinels into the real ~/.claude/logs.
DERIVED_GROWTH_WARN_DIR: Optional[Path] = None


def derived_growth_warn_dir() -> Path:
    return DERIVED_GROWTH_WARN_DIR or (paths.logs() / ".derived_channel_growth_warnings")


def slow_hook_threshold_s() -> float:
    """SLOW_HOOK_SECONDS, overridable via SESSION_LOGGER_SLOW_HOOK_SECONDS
    (a float; anything unparsable falls back to the default)."""
    raw = os.environ.get("SESSION_LOGGER_SLOW_HOOK_SECONDS")
    if raw is None:
        return SLOW_HOOK_SECONDS
    try:
        return float(raw)
    except ValueError:
        return SLOW_HOOK_SECONDS


def perf_log_path() -> Path:
    """`<claude_dir>/logs/session-logger-perf.log`, resolved at CALL time so a
    relocated CLAUDE_DIR (or an isolated test home) is honored."""
    return paths.logs() / PERF_LOG_NAME


def perf_log(line: str) -> None:
    """Append one line to session-logger-perf.log. Best-effort, never raises."""
    try:
        target = perf_log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S.%f}: {line}\n")
    except Exception:
        pass


class PerfTimer:
    """Wall-clock phases of one hook invocation: `mark(label)` closes the
    phase that began at the previous mark; `report(...)` writes a SLOW line
    when the total exceeds the threshold."""

    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self._last = self._t0
        self._phases: list[tuple[str, float]] = []

    def mark(self, label: str) -> None:
        now = time.perf_counter()
        self._phases.append((label, now - self._last))
        self._last = now

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._t0

    def report(self, session_id: str, event: str, tool: str,
               threshold_s: Optional[float] = None, extra: str = "") -> bool:
        """Write the SLOW line when elapsed exceeds the threshold; True if written."""
        threshold = slow_hook_threshold_s() if threshold_s is None else threshold_s
        elapsed = self.elapsed
        if elapsed <= threshold:
            return False
        phases = " ".join(f"{label}={dt:.3f}" for label, dt in self._phases)
        perf_log(f"SLOW session={session_id[:8]} event={event} tool={tool or '-'} "
                 f"elapsed={elapsed:.3f}s {phases} {extra}".rstrip())
        return True


def inflight_dir() -> Path:
    return paths.session_states() / "inflight"


def begin_inflight(session_id: str, event: str, tool: str) -> Optional[Path]:
    """Leave a marker for this invocation; end_inflight() removes it. A marker
    still present later means the invocation never finished (killed)."""
    try:
        d = inflight_dir()
        d.mkdir(parents=True, exist_ok=True)
        marker = d / f"{session_id}__{os.getpid()}.inflight"
        marker.write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S.%f} {event} {tool or '-'}\n",
                          encoding="utf-8")
        return marker
    except Exception:
        return None


def end_inflight(marker: Optional[Path]) -> None:
    if marker is None:
        return
    try:
        marker.unlink()
    except Exception:
        pass


def report_stale_inflight(stale_after_s: Optional[float] = None) -> int:
    """Report every in-flight marker older than `stale_after_s` (once -- the
    marker is removed after reporting). Returns the number reported."""
    threshold = STALE_INFLIGHT_SECONDS if stale_after_s is None else stale_after_s
    d = inflight_dir()
    if not d.exists():
        return 0
    try:
        entries = list(os.scandir(d))
    except OSError:
        return 0
    reported = 0
    now = datetime.now()
    for entry in entries:
        if not entry.name.endswith(".inflight"):
            continue
        parts: list[str] = []
        try:
            parts = Path(entry.path).read_text(encoding="utf-8").strip().split(" ")
            stamp = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            try:
                stamp = datetime.fromtimestamp(entry.stat().st_mtime)
            except OSError:
                continue
        age = (now - stamp).total_seconds()
        if age <= threshold:
            continue
        session_id, _, pid = entry.name[:-len(".inflight")].partition("__")
        event = parts[2] if len(parts) > 2 else "?"
        tool = parts[3] if len(parts) > 3 else "-"
        perf_log(f"DID-NOT-FINISH session={session_id[:8]} event={event} tool={tool} "
                 f"started={stamp:%Y-%m-%d %H:%M:%S} age={age:.0f}s pid={pid} "
                 f"-- probably killed by the hook timeout")
        reported += 1
        try:
            os.unlink(entry.path)
        except OSError:
            pass
    return reported


def _warn_derived_growth_once(session_id: str, count: int) -> None:
    """Once per session: the directory has grown more than
    DERIVED_CHANNEL_WARN_THRESHOLD derived channel basenames -- the shape of
    the 2026-09-02 incident (one basename per untyped agent). Observability
    only; routing is never changed here."""
    try:
        warn_dir = derived_growth_warn_dir()
        warn_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_\-.]", "_", session_id)
        sentinel = warn_dir / f"{safe}.warned"
        try:
            sentinel.open("x").close()
        except FileExistsError:
            return
        msg = (f"DERIVED-GROWTH session={session_id[:8]} derived_basenames={count} "
               f"threshold={DERIVED_CHANNEL_WARN_THRESHOLD} -- is an axis producing "
               f"identifier-shaped subtypes? (see docs/configuration.md, subtype_split)")
        debug_log(msg)
        perf_log(msg)
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
