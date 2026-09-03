"""Reconciliation gating + single-pass scan (2026-09-02 incident, unit U2).

Before: `reconcile_session_files` ran on EVERY hook event and, for each
basename it discovered on disk, re-listed the directory with a `stat()` per
entry (`Path.iterdir()` + `is_file()`). One basename per file (the untyped
agents) made that O(files^2): 0.18s at 0 files, 16.6s at 600, ~56s at 1,100
-- the 60s hook kills and the 30s UserPromptSubmit timeout.

After: one `os.scandir` listing per reconciliation (no per-entry stat -- the
directory entry already knows it is a file), and a per-directory stamp
(`.session-logger-reconciled`) holding the effective session name the files
currently embed, so the steady state does no listing at all. The first event
of each run always reconciles (self-heal for hand renames between runs).

Design: 2026-09-02__16-03-52__dev-workflow-process__untyped-subagent-bucketing-and-reconciliation-gating.md
(project-private; AC-2, AC-4). Probe B of
tests/one-offs/thinking/repro_agent_spam_and_timeout.py graduated below.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO / "hooks" / "scripts" / "log-command.py"
GUID = "c0dec0de-0902-4bbb-8ccc-0000000000b2"
USER = "gateuser"
SHELL = "bash.exe"
CHANNELS = ["sesslog", "shell", "tasks", "tools", "convo", "unknowns", "agents", "fileio"]


def _log_name(basename: str, name: str | None, seq: int | None = None) -> str:
    if name is None:
        return f".{basename}_{SHELL}_{GUID}_{USER}.log"
    mid = f"{name}--{seq:03d}" if seq is not None else name
    return f".{basename}_{SHELL}__{mid}__{GUID}_{USER}.log"


def _seed(d: Path, n_derived: int, name: str | None) -> None:
    for base in ("sesslog", "shell", "tools", "agents"):
        (d / _log_name(base, name)).write_text("x\n", encoding="utf-8")
    for i in range(n_derived):
        (d / _log_name(f"agents-a{i:016x}", name)).write_text("x\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_home_for_every_test(tmp_path, monkeypatch):
    """Every test here runs against tmp dirs, but the reconciliation pass can
    emit a derived-growth warning that writes to the PERF LOG and a warn-dir
    under the home directory -- resolved at call time from HOME. Point HOME at
    the tmp dir so nothing reaches the real ~/.claude (a leak the 1,000-file
    ladder actually caused on its first run)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)


class _Counter:
    """Count os.scandir / os.listdir / os.stat calls made during a block."""

    def __init__(self, monkeypatch):
        self.scandir = 0
        self.listdir = 0
        self.stat = 0
        real_scandir, real_listdir, real_stat = os.scandir, os.listdir, os.stat

        def scandir(*a, **k):
            self.scandir += 1
            return real_scandir(*a, **k)

        def listdir(*a, **k):
            self.listdir += 1
            return real_listdir(*a, **k)

        def stat(*a, **k):
            self.stat += 1
            return real_stat(*a, **k)

        monkeypatch.setattr(os, "scandir", scandir)
        monkeypatch.setattr(os, "listdir", listdir)
        monkeypatch.setattr(os, "stat", stat)


# ============================================================================
# AC-2: one listing, no per-entry stat, linear in the file count
# ============================================================================

class TestSinglePassScan:
    def test_steady_state_is_one_listing_and_no_per_entry_stat(self, tmp_path, monkeypatch):
        from cclogger.reconciliation import reconcile_session_files
        n = 1000
        _seed(tmp_path, n, "newname")
        c = _Counter(monkeypatch)
        targets = reconcile_session_files(tmp_path, GUID, "newname", SHELL, USER,
                                          channel_names=CHANNELS)
        assert c.scandir == 1, c.scandir
        assert c.listdir == 0, c.listdir
        assert c.stat <= n + 4, c.stat          # AC-2: <= files + 4
        assert set(targets) >= {"sesslog", "shell", "agents"}

    def test_rename_pass_is_linear(self, tmp_path, monkeypatch):
        """1,000 derived files under the old name -> all renamed in one pass."""
        from cclogger.reconciliation import reconcile_session_files
        n = 1000
        _seed(tmp_path, n, "oldname")
        c = _Counter(monkeypatch)
        t0 = time.perf_counter()
        reconcile_session_files(tmp_path, GUID, "newname", SHELL, USER,
                                channel_names=CHANNELS)
        dt = time.perf_counter() - t0
        scandir, listdir, stat = c.scandir, c.listdir, c.stat  # before our own listing below
        names = [p.name for p in tmp_path.iterdir()]
        assert all("__newname__" in nm for nm in names if nm.startswith(".agents-a")), names[:3]
        assert not any("oldname" in nm for nm in names)
        assert scandir == 1
        assert listdir == 0
        assert stat <= 2 * (n + 4) + 4            # one exists() per rename, at most
        assert dt < 5.0, dt

    def test_cost_is_flat_across_the_ladder(self, tmp_path):
        """In-process ladder (the quadratic term is gone): 1,000 files must not
        cost more than 20x the 0-file case -- generous, because the 0-file
        case is microseconds and timer noise dominates."""
        from cclogger.reconciliation import reconcile_session_files
        times = {}
        for n in (0, 1000):
            d = tmp_path / f"n{n}"
            d.mkdir()
            _seed(d, n, "newname")
            t0 = time.perf_counter()
            reconcile_session_files(d, GUID, "newname", SHELL, USER, channel_names=CHANNELS)
            times[n] = time.perf_counter() - t0
        assert times[1000] < 1.0, times

    def test_targets_and_sequencing_semantics_unchanged(self, tmp_path):
        """Two files for one channel: newest becomes the target, older gets
        the first sequence (--000, the pre-existing convention: max_seq
        starts at -1); subtype derivatives renamed in place but not in
        targets."""
        from cclogger.reconciliation import reconcile_session_files
        older = tmp_path / _log_name("sesslog", None)
        older.write_text("old\n", encoding="utf-8")
        os.utime(older, (1_600_000_000, 1_600_000_000))
        newer = tmp_path / _log_name("sesslog", "oldname")
        newer.write_text("new\n", encoding="utf-8")
        (tmp_path / _log_name("shell-bash", "oldname")).write_text("x\n", encoding="utf-8")
        targets = reconcile_session_files(tmp_path, GUID, "newname", SHELL, USER,
                                          channel_names=["sesslog", "shell"])
        names = sorted(p.name for p in tmp_path.iterdir())
        assert _log_name("sesslog", "newname") in names
        assert _log_name("sesslog", "newname", 0) in names
        assert _log_name("shell-bash", "newname") in names
        assert targets["sesslog"] == tmp_path / _log_name("sesslog", "newname")
        assert "shell-bash" not in targets

    def test_sequence_assignment_uses_the_highest_existing_sequence(self, tmp_path):
        """Kills mutant M6 (max -> min in find_max_sequence): with --000 and
        --001 already taken, the next unsequenced older file must get --002;
        under `min` the assignment collides with --000 and the rename fails."""
        from cclogger.reconciliation import reconcile_session_files
        for seq in (0, 1):
            p = tmp_path / _log_name("sesslog", "newname", seq)
            p.write_text("s\n", encoding="utf-8")
            os.utime(p, (1_600_000_000 + seq, 1_600_000_000 + seq))
        older = tmp_path / _log_name("sesslog", None)
        older.write_text("old\n", encoding="utf-8")
        os.utime(older, (1_600_000_100, 1_600_000_100))
        newest = tmp_path / _log_name("sesslog", "oldname")
        newest.write_text("new\n", encoding="utf-8")
        os.utime(newest, (1_600_000_200, 1_600_000_200))
        reconcile_session_files(tmp_path, GUID, "newname", SHELL, USER, channel_names=["sesslog"])
        names = sorted(p.name for p in tmp_path.iterdir())
        assert _log_name("sesslog", "newname", 2) in names, names
        assert _log_name("sesslog", None) not in names, names

    def test_discover_never_yields_an_empty_basename(self, tmp_path):
        """Kills mutant M8 (`+` -> `*` in the discover regex): a malformed
        `._...` file must not be discovered as channel basename ''."""
        from cclogger.reconciliation import discover_channel_basenames
        (tmp_path / f"._{SHELL}__weird__{GUID}_{USER}.log").write_text("x\n", encoding="utf-8")
        (tmp_path / _log_name("tools", "weird")).write_text("x\n", encoding="utf-8")
        found = discover_channel_basenames(tmp_path, GUID)
        assert "" not in found and "tools" in found, found


# ============================================================================
# AC-4: the stamp -- steady state skips the listing; changes and new runs don't
# ============================================================================

@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _logger(name: str):
    from cclogger.logger import SessionLogger
    from cclogger.models import Config, SessionContext
    session = SessionContext(shell_type=SHELL, session_name=name,
                             session_id=GUID, username=USER)
    return SessionLogger(Config(), session, datetime(2026, 9, 3, 1, 0, 0))


class TestStampGate:
    def test_stamp_holds_the_effective_name_after_reconcile(self, isolated_home):
        from cclogger.reconciliation import RECONCILED_STAMP
        lg = _logger("first-name")
        stamp = lg.session_dir / RECONCILED_STAMP
        assert stamp.exists()
        assert stamp.read_text(encoding="utf-8").strip() == lg.effective_name

    def test_steady_state_does_not_list_the_directory(self, isolated_home, monkeypatch):
        lg = _logger("first-name")
        lg.unified_log_path.write_text("x\n", encoding="utf-8")
        # first event of the run wrote the marker -> run is now "started"
        assert lg.session_dir.exists()
        c = _Counter(monkeypatch)
        lg2 = _logger("first-name")           # same run, same name -> steady state
        assert c.scandir == 0 and c.listdir == 0, (c.scandir, c.listdir)
        assert lg2.unified_log_path == lg.unified_log_path

    def test_name_change_reconciles_every_file_including_derived(self, isolated_home):
        from cclogger.reconciliation import RECONCILED_STAMP
        lg = _logger("first-name")
        d = lg.session_dir
        (d / _log_name("agents-a0000000000000aa", lg.effective_name)).write_text("x\n", encoding="utf-8")
        lg.unified_log_path.write_text("x\n", encoding="utf-8")
        lg2 = _logger("second-name")          # rename path: dir + files + stamp
        d2 = lg2.session_dir
        names = [p.name for p in d2.iterdir()]
        assert any(nm.startswith(".agents-a0000000000000aa_") and lg2.effective_name in nm for nm in names), names
        assert not any("first-name" in nm for nm in names if nm.startswith("."))
        assert (d2 / RECONCILED_STAMP).read_text(encoding="utf-8").strip() == lg2.effective_name

    def test_new_run_reconciles_even_when_stamp_matches(self, isolated_home):
        """Self-heal: a file hand-renamed to the unnamed form between runs is
        picked up on the first event of the next run despite a fresh stamp."""
        from cclogger import paths
        lg = _logger("first-name")
        d = lg.session_dir
        stray = d / _log_name("tools", None)  # unnamed form, wrong for a named session
        stray.write_text("x\n", encoding="utf-8")
        (paths.session_states() / f"{GUID}.started").unlink(missing_ok=True)  # new run
        _logger("first-name")
        names = [p.name for p in d.iterdir()]
        assert _log_name("tools", None) not in names
        assert any(nm.startswith(".tools_") and lg.effective_name in nm for nm in names), names


# ============================================================================
# Probe B graduated: the hook's wall time no longer grows with the file count
# ============================================================================

def _drive(home: Path, payload: dict) -> float:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["USERNAME"] = USER
    env["USER"] = USER
    for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR", "TMUX"):
        env.pop(k, None)
    site = str(Path.home() / ".local" / "lib" /
               f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")
    env["PYTHONPATH"] = site + os.pathsep + env.get("PYTHONPATH", "")
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, str(HOOK_SCRIPT)],
                          input=json.dumps(payload).encode("utf-8"),
                          capture_output=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr.decode()[:800]
    return time.perf_counter() - t0


class TestHookLadder:
    def test_thousand_derived_files_cost_no_more_than_twice_the_empty_dir(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        transcript = home / "t.jsonl"
        transcript.write_text('{"type":"user"}\n', encoding="utf-8")
        base = {"session_id": GUID, "transcript_path": str(transcript),
                "cwd": str(REPO), "permission_mode": "default"}
        tool = dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                    tool_input={"command": "echo x"},
                    tool_response={"stdout": "x", "stderr": "", "interrupted": False})
        _drive(home, dict(base, hook_event_name="SessionStart", source="startup"))
        _drive(home, tool)
        d = next(p for p in (home / ".claude" / "sesslogs").iterdir() if GUID in p.name)
        sesslog = next(iter(d.glob(".sesslog_*")))
        tail = sesslog.name.split("_", 1)[1]       # live naming tail
        t_empty = statistics.median(_drive(home, tool) for _ in range(3))
        for i in range(1000):
            (d / f".agents-a{i:016x}_{tail}").write_text("x\n", encoding="utf-8")
        t_full = statistics.median(_drive(home, tool) for _ in range(3))
        assert t_full <= 2 * t_empty + 0.15, (t_empty, t_full)
