"""Hook observability (unit U5, 2026-09-02 incident): the hook records its
own slow invocations, reports a previous invocation that never finished
(the only trace a hook-timeout kill leaves), and warns once when a session
grows an unusual number of derived channels.

Maintainer (verbatim, 2026-09-02): "if we hit timeouts we should be noting
them somewhere in our error log (if we aren't already) so we can figure out
whether or not we need to improve our log design".

Design: 2026-09-02__16-03-52__dev-workflow-process__untyped-subagent-bucketing-and-reconciliation-gating.md
(project-private; Addendum 3, AC-8, AC-9).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO / "hooks" / "scripts" / "log-command.py"
GUID = "0b5e0b5e-0902-4bbb-8ccc-0000000000e5"
USER = "obsuser"
SHELL = "bash.exe"


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


# ============================================================================
# AC-8a: slow-invocation record with a phase breakdown
# ============================================================================

class TestPerfTimer:
    def test_only_slow_invocations_are_recorded(self, isolated_home, monkeypatch):
        from cclogger import debug, paths
        perf = paths.logs() / "session-logger-perf.log"
        t = debug.PerfTimer()
        t.mark("parsed")
        t.mark("logged")
        t.report(session_id=GUID, event="PostToolUse", tool="Bash", threshold_s=10.0)
        assert not perf.exists()
        t2 = debug.PerfTimer()
        t2.mark("parsed")
        time.sleep(0.02)
        t2.mark("logged")
        t2.report(session_id=GUID, event="PostToolUse", tool="Bash", threshold_s=0.0)
        line = perf.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert "SLOW" in line and "event=PostToolUse" in line and "tool=Bash" in line
        assert GUID[:8] in line
        assert "parsed=" in line and "logged=" in line     # phase breakdown
        assert "elapsed=" in line

    def test_env_override_of_threshold(self, monkeypatch):
        from cclogger import debug
        monkeypatch.setenv("SESSION_LOGGER_SLOW_HOOK_SECONDS", "0.25")
        assert debug.slow_hook_threshold_s() == 0.25
        monkeypatch.setenv("SESSION_LOGGER_SLOW_HOOK_SECONDS", "not-a-number")
        assert debug.slow_hook_threshold_s() == debug.SLOW_HOOK_SECONDS


# ============================================================================
# AC-8b: an invocation that never finished is reported by the next one
# ============================================================================

class TestInflightSentinel:
    def test_stale_inflight_is_reported_once_and_cleared(self, isolated_home):
        from cclogger import debug, paths
        stale = debug.inflight_dir() / f"{GUID}__424242.inflight"
        stale.parent.mkdir(parents=True, exist_ok=True)
        started = datetime.now() - timedelta(minutes=10)
        stale.write_text(f"{started:%Y-%m-%d %H:%M:%S.%f} PostToolUse Bash\n", encoding="utf-8")
        debug.report_stale_inflight(stale_after_s=120.0)
        perf = paths.logs() / "session-logger-perf.log"
        text = perf.read_text(encoding="utf-8")
        assert "DID-NOT-FINISH" in text and "PostToolUse" in text and "Bash" in text
        assert not stale.exists()
        debug.report_stale_inflight(stale_after_s=120.0)       # nothing left to report
        assert perf.read_text(encoding="utf-8") == text

    def test_fresh_inflight_is_left_alone(self, isolated_home):
        from cclogger import debug, paths
        fresh = debug.inflight_dir() / f"{GUID}__1.inflight"
        fresh.parent.mkdir(parents=True, exist_ok=True)
        fresh.write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S.%f} Stop -\n", encoding="utf-8")
        debug.report_stale_inflight(stale_after_s=120.0)
        assert fresh.exists()
        assert not (paths.logs() / "session-logger-perf.log").exists()

    def test_begin_and_end_bracket_an_invocation(self, isolated_home):
        from cclogger import debug
        marker = debug.begin_inflight(GUID, "PostToolUse", "Bash")
        assert marker.exists() and "PostToolUse Bash" in marker.read_text(encoding="utf-8")
        debug.end_inflight(marker)
        assert not marker.exists()


# ============================================================================
# AC-9: derived-channel growth warn-once (observability, never rerouting)
# ============================================================================

class TestDerivedGrowthWarnOnce:
    def _reconcile_with(self, d: Path, n_derived: int, monkeypatch):
        import cclogger.debug as dbg
        from cclogger.reconciliation import reconcile_session_files
        # Isolation: the warning also writes to the perf log, which resolves
        # its path from the home at CALL time -- point HOME at the tmp dir so
        # nothing reaches the real ~/.claude/logs (a leak the first run of
        # these tests actually caused).
        monkeypatch.setenv("HOME", str(d))
        monkeypatch.setenv("USERPROFILE", str(d))
        for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setattr(dbg, "DERIVED_GROWTH_WARN_DIR", d / "warn")
        tail = f"{SHELL}__name__{GUID}_{USER}.log"
        (d / f".sesslog_{tail}").write_text("x\n", encoding="utf-8")
        for i in range(n_derived):
            (d / f".tools-srv{i:04d}_{tail}").write_text("x\n", encoding="utf-8")
        reconcile_session_files(d, GUID, "name", SHELL, USER, channel_names=["sesslog", "tools"])
        return sorted(p.name for p in (d / "warn").glob("*.warned")) if (d / "warn").exists() else []

    def test_sixty_five_derived_channels_warn_exactly_once(self, tmp_path, monkeypatch):
        assert self._reconcile_with(tmp_path, 65, monkeypatch) == [f"{GUID}.warned"]
        # second pass: still one sentinel, no second warning
        from cclogger.reconciliation import reconcile_session_files
        reconcile_session_files(tmp_path, GUID, "name", SHELL, USER, channel_names=["sesslog", "tools"])
        assert sorted(p.name for p in (tmp_path / "warn").glob("*.warned")) == [f"{GUID}.warned"]

    def test_sixty_three_do_not_warn(self, tmp_path, monkeypatch):
        assert self._reconcile_with(tmp_path, 63, monkeypatch) == []

    def test_warning_never_changes_routing(self, tmp_path, monkeypatch):
        """AC-9 is observability only: every derived file is still reconciled."""
        self._reconcile_with(tmp_path, 70, monkeypatch)
        names = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tools-srv")]
        assert len(names) == 70


# ============================================================================
# End to end: the hook brackets itself and records slow runs
# ============================================================================

def _drive(home: Path, payload: dict, extra_env: dict | None = None) -> None:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["USERNAME"] = USER
    env["USER"] = USER
    for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR", "TMUX", "SESSION_LOGGER_SLOW_HOOK_SECONDS"):
        env.pop(k, None)
    env.update(extra_env or {})
    site = str(Path.home() / ".local" / "lib" /
               f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")
    env["PYTHONPATH"] = site + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, str(HOOK_SCRIPT)],
                          input=json.dumps(payload).encode("utf-8"),
                          capture_output=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode()[:800]


class TestHookEndToEnd:
    def _base(self, home: Path) -> dict:
        transcript = home / "t.jsonl"
        transcript.write_text('{"type":"user"}\n', encoding="utf-8")
        return {"session_id": GUID, "transcript_path": str(transcript),
                "cwd": str(REPO), "permission_mode": "default"}

    def test_slow_threshold_zero_records_every_invocation_with_phases(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        base = self._base(home)
        tool = dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                    tool_input={"command": "echo x"},
                    tool_response={"stdout": "x", "stderr": "", "interrupted": False})
        _drive(home, dict(base, hook_event_name="SessionStart", source="startup"))
        _drive(home, tool, {"SESSION_LOGGER_SLOW_HOOK_SECONDS": "0"})
        perf = home / ".claude" / "logs" / "session-logger-perf.log"
        text = perf.read_text(encoding="utf-8")
        assert "SLOW" in text and "event=PostToolUse" in text and "tool=Bash" in text
        assert "logger-init=" in text and "log-entry=" in text
        # no in-flight marker survives a finished invocation
        inflight = home / ".claude" / "session-states" / "inflight"
        assert not inflight.exists() or list(inflight.iterdir()) == []

    def test_previous_kill_is_reported_by_the_next_invocation(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        base = self._base(home)
        _drive(home, dict(base, hook_event_name="SessionStart", source="startup"))
        inflight = home / ".claude" / "session-states" / "inflight"
        inflight.mkdir(parents=True, exist_ok=True)
        started = datetime.now() - timedelta(minutes=5)
        (inflight / f"{GUID}__99999.inflight").write_text(
            f"{started:%Y-%m-%d %H:%M:%S.%f} UserPromptSubmit -\n", encoding="utf-8")
        _drive(home, dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                          tool_input={"command": "echo y"},
                          tool_response={"stdout": "y", "stderr": "", "interrupted": False}))
        text = (home / ".claude" / "logs" / "session-logger-perf.log").read_text(encoding="utf-8")
        assert "DID-NOT-FINISH" in text and "UserPromptSubmit" in text
        assert list(inflight.iterdir()) == []
