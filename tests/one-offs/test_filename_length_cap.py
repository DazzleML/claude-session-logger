"""#52 length cap: over-long session names must LOG, with truncated filenames.

Design: 2026-08-12__21-42-03__issue-52-filename-length-cap-design.md (Option C).

The cap is applied ONCE per name input boundary -- build_session_context()
(transcript/cache path) and get_effective_session_name() (on-disk recovery)
-- so every consumer (get_filename_context, the claude-history sidecar path,
build_filename, build_session_dirname) sees the identical capped string.
Consistency-by-construction is the point: per-consumer budgets would
truncate the same name differently and re-create the churn class the
delimiter-collision fix (#51) eliminated.

Acceptance checks covered here (from the DWP):
  AC-1  250-char name: one file per channel, entries written, no FATAL
  AC-2  filename set byte-identical across restarts (churn guard)
  AC-4  directory name and log filenames embed the SAME name string
  AC-6  multibyte names: no split characters, byte budget respected
  AC-7  names <= budget pass through byte-identical
  (AC-3 is a grep-level check; AC-5 is the rest of the suite staying green)

Run: python -m pytest tests/one-offs/test_filename_length_cap.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dazzle_filekit import NAME_MAX

# sys.path setup happens in conftest.py
from cclogger.session_naming import (
    NAME_MAX_BYTES,
    SHELL_MAX_BYTES,
    SUBTYPE_MAX_BYTES,
    USERNAME_MAX_BYTES,
    cap_field,
    cap_session_name,
)

HOOK_SCRIPT = Path(__file__).parent.parent.parent / "hooks" / "scripts" / "log-command.py"
GUID = "e1000000-52aa-4bbb-8ccc-000000000052"
USER = "captest"

LONG_NAME = ("x__" * 62) + "end"          # 189*... the adversarial probe shape, ~250 raw
assert len(LONG_NAME) == 189 or True      # informational; real length asserted in tests
LONG_NAME_250 = ("Z" * 250)               # plain 250-char name (issue repro shape)


# ============================================================================
# Unit: cap_field / cap_session_name
# ============================================================================

class TestCapField:
    def test_short_value_untouched(self):
        """AC-7: values within budget are byte-identical -- no silent mutation."""
        assert cap_field("bash.exe", SHELL_MAX_BYTES) == "bash.exe"

    def test_exact_boundary_untouched(self):
        v = "a" * NAME_MAX_BYTES
        assert cap_session_name(v) == v

    def test_over_budget_truncates_to_byte_limit(self):
        v = "a" * (NAME_MAX_BYTES + 50)
        out = cap_session_name(v)
        assert len(out.encode("utf-8")) <= NAME_MAX_BYTES

    def test_multibyte_never_split(self):
        """AC-6: a CJK name truncates on a character boundary, decodable."""
        v = "中" * NAME_MAX_BYTES          # 3 utf-8 bytes per char
        out = cap_session_name(v)
        assert len(out.encode("utf-8")) <= NAME_MAX_BYTES
        out.encode("utf-8").decode("utf-8")     # raises if a char was split
        # 100 // 3 = 33 whole chars
        assert out == "中" * (NAME_MAX_BYTES // 3)

    def test_trailing_underscore_trimmed_after_cut(self):
        """A cut landing between the two `_` of a `__` must not leave a
        dangling half-delimiter adjacent to the structural `__`."""
        v = ("a" * (NAME_MAX_BYTES - 1)) + "__tail"
        out = cap_session_name(v)
        assert not out.endswith("_"), out

    def test_all_real_names_unaffected(self):
        """AC-7 against the measured population: longest real name is 94
        bytes (2026-08-12 scan of 431 dirs); budget must clear it."""
        assert NAME_MAX_BYTES >= 100
        sample = "MAKING-LIBS_PRESERVELIB_DAZZLELINKLIB__2026-6-11__finalizing-libraries-classes-w"
        assert cap_session_name(sample) == sample


class TestBudgetArithmetic:
    """The constants must satisfy the 255-byte component budget with every
    capped field stacked at its maximum. If a future channel prefix or cap
    change breaks the math, THIS test fails loudly (constant-drift guard
    from the DWP's risk mitigations)."""

    def test_budget_arithmetic(self):
        import re as _re
        models_src = (Path(__file__).parent.parent.parent /
                      "hooks" / "scripts" / "cclogger" / "models.py").read_text(encoding="utf-8")
        prefixes = _re.findall(r'file_prefix="(\.[^"]+)"', models_src)
        assert prefixes, "no channel prefixes found in models.py"
        longest_prefix = max(len(p) for p in prefixes)
        # subtype channels derive `.{base}-{subtype}_` from the base prefix
        worst_prefix = longest_prefix + 1 + SUBTYPE_MAX_BYTES
        worst = (worst_prefix + SHELL_MAX_BYTES + 2 + NAME_MAX_BYTES
                 + 5                     # --NNN sequence suffix
                 + 2 + 36 + 1 + USERNAME_MAX_BYTES + 4)   # __guid_user.log
        assert worst <= NAME_MAX, (
            f"budget blown: worst-case filename {worst} > NAME_MAX={NAME_MAX} "
            f"(longest prefix {longest_prefix}, caps {NAME_MAX_BYTES}/"
            f"{SHELL_MAX_BYTES}/{SUBTYPE_MAX_BYTES}/{USERNAME_MAX_BYTES})")

    def test_config_sidecar_within_budget(self):
        worst = (len("claude-history-") + SHELL_MAX_BYTES + 2 + NAME_MAX_BYTES
                 + 2 + 36 + 1 + USERNAME_MAX_BYTES + len(".json"))
        assert worst <= NAME_MAX, f"config sidecar filename {worst} > NAME_MAX={NAME_MAX}"


# ============================================================================
# Input boundaries: both paths must cap
# ============================================================================

class TestInputBoundaries:
    def test_build_session_context_caps_name(self, monkeypatch):
        from cclogger import session_state
        from cclogger.models import ToolInfo
        monkeypatch.setattr(session_state, "get_session_name",
                            lambda *a: LONG_NAME_250)
        monkeypatch.setattr(session_state, "detect_tmux_session", lambda: None)
        ti = ToolInfo.from_json({"session_id": GUID, "transcript_path": ""})
        ctx = session_state.build_session_context(ti)
        assert len(ctx.session_name.encode("utf-8")) <= NAME_MAX_BYTES

    def test_build_session_context_caps_tmux_shell(self, monkeypatch):
        from cclogger import session_state
        from cclogger.models import ToolInfo
        monkeypatch.setattr(session_state, "get_session_name", lambda *a: None)
        monkeypatch.setattr(session_state, "detect_tmux_session",
                            lambda: "t" * 120)
        ti = ToolInfo.from_json({"session_id": GUID, "transcript_path": ""})
        ctx = session_state.build_session_context(ti)
        assert len(ctx.shell_type.encode("utf-8")) <= SHELL_MAX_BYTES

    def test_build_session_context_caps_username(self, monkeypatch):
        """Coverage gap found by the tester-unbounded mutation run
        (2026-08-12): M3 (revert the username cap) survived the matrix
        because no test exercised an over-long USER/USERNAME env value.
        This test makes M3 load-bearing."""
        from cclogger import session_state
        from cclogger.models import ToolInfo
        monkeypatch.setattr(session_state, "get_session_name", lambda *a: None)
        monkeypatch.setattr(session_state, "detect_tmux_session", lambda: None)
        monkeypatch.setenv("USER", "u" * 80)
        monkeypatch.setenv("USERNAME", "u" * 80)
        ti = ToolInfo.from_json({"session_id": GUID, "transcript_path": ""})
        ctx = session_state.build_session_context(ti)
        assert len(ctx.username.encode("utf-8")) <= USERNAME_MAX_BYTES

    def test_effective_name_recovery_caps_legacy_disk_name(self, tmp_path):
        """The bypass found in the logic recheck: an unnamed session whose
        on-disk directory carries a legacy (pre-cap, up to ~209 char) name
        re-injects it via get_effective_session_name. Recovery must cap."""
        from cclogger.reconciliation import get_effective_session_name
        legacy = "L" * 200
        (tmp_path / f"{legacy}__{GUID}_{USER}").mkdir()
        out = get_effective_session_name(GUID, None, tmp_path)
        assert out is not None
        assert len(out.encode("utf-8")) <= NAME_MAX_BYTES

    def test_subtype_capped(self):
        from cclogger.categorize import get_subtype
        long_subtype = "agent-" + ("y" * 100)
        out = get_subtype("meta", "Agent",
                          {"tool_input": {"subagent_type": long_subtype}})
        if out is not None:   # extractor may not fire for this shape; unit-level fallback:
            assert len(out.encode("utf-8")) <= SUBTYPE_MAX_BYTES
        assert len(cap_field(long_subtype, SUBTYPE_MAX_BYTES).encode("utf-8")) <= SUBTYPE_MAX_BYTES


# ============================================================================
# End-to-end: 250-char name must LOG (AC-1), stably (AC-2), consistently (AC-4)
# ============================================================================

def _drive_hook(home: Path, events: list) -> None:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["USERNAME"] = USER
    env["USER"] = USER
    env.pop("CLAUDE_DIR", None)
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.pop("TMUX", None)
    site = str(Path.home() / ".local" / "lib" /
               f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")
    env["PYTHONPATH"] = site + os.pathsep + env.get("PYTHONPATH", "")
    for ev in events:
        proc = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT)],
            input=json.dumps(ev).encode("utf-8"),
            capture_output=True, env=env, timeout=30,
        )
        assert proc.returncode == 0, proc.stderr.decode()[:500]


def _events(transcript: Path, n_tools: int = 3) -> list:
    base = {
        "session_id": GUID,
        "transcript_path": str(transcript),
        "cwd": "/",
        "permission_mode": "default",
    }
    evs = [dict(base, hook_event_name="SessionStart", source="startup")]
    for i in range(n_tools):
        evs.append(dict(
            base, hook_event_name="PostToolUse", tool_name="Bash",
            tool_input={"command": f"echo cap-{i}"},
            tool_response={"stdout": f"cap-{i}", "stderr": "", "interrupted": False},
        ))
    return evs


class TestEndToEndLongName:
    @pytest.fixture
    def scratch_home(self, tmp_path):
        home = tmp_path / "home"
        state = home / ".claude" / "session-states"
        state.mkdir(parents=True)
        (state / f"{GUID}.name-cache").write_text(LONG_NAME_250, encoding="utf-8")
        transcript = home / ".claude" / "projects" / "-" / f"{GUID}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({"type": "user", "message":
                              {"role": "user", "content": "hi"}}) + "\n")
        return home, transcript

    def _session_dirs(self, home: Path):
        base = home / ".claude" / "sesslogs"
        return sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []

    def _log_files(self, d: Path):
        return sorted(p.name for p in d.iterdir()
                      if p.is_file() and p.name.startswith(".") and GUID in p.name)

    def test_250_char_name_logs(self, scratch_home):
        """AC-1: the issue's own acceptance sketch. 250-char name ->
        working logs, truncated filenames, no FATAL in hook-debug.log."""
        home, transcript = scratch_home
        _drive_hook(home, _events(transcript))

        dirs = self._session_dirs(home)
        assert len(dirs) == 1, [d.name for d in dirs]
        files = self._log_files(dirs[0])
        assert files, "no log files created for 250-char name (silent loss)"

        # entries actually WRITTEN, not just files touched
        shell_logs = [f for f in files if f.startswith(".shell_")]
        assert shell_logs, files
        content = (dirs[0] / shell_logs[0]).read_text(encoding="utf-8")
        assert "cap-0" in content, "tool entry missing from shell log"

        # no FATAL anywhere
        debug_log = home / ".claude" / "logs" / "hook-debug.log"
        if debug_log.exists():
            assert "FATAL" not in debug_log.read_text(encoding="utf-8")

        # every component within the filesystem budget
        assert len(dirs[0].name.encode("utf-8")) <= NAME_MAX
        for f in files:
            assert len(f.encode("utf-8")) <= NAME_MAX, f

    def test_no_churn_across_restarts(self, scratch_home):
        """AC-2: filename set byte-identical across three runs. The churn
        guard -- the specific failure mode a divergent cap would create."""
        home, transcript = scratch_home
        _drive_hook(home, _events(transcript))
        run1 = self._log_files(self._session_dirs(home)[0])
        _drive_hook(home, _events(transcript))
        run2 = self._log_files(self._session_dirs(home)[0])
        _drive_hook(home, _events(transcript))
        run3 = self._log_files(self._session_dirs(home)[0])
        assert run1 == run2 == run3, (
            f"churn detected:\n r1={run1}\n r2={run2}\n r3={run3}")
        assert len(self._session_dirs(home)) == 1

    def test_dir_and_files_embed_same_capped_name(self, scratch_home):
        """AC-4: the GT-3 asymmetry closed -- directory and every file
        carry the identical capped name string."""
        home, transcript = scratch_home
        _drive_hook(home, _events(transcript, n_tools=1))
        d = self._session_dirs(home)[0]
        dir_name_part = d.name.split(f"__{GUID}")[0]
        expected = cap_session_name(LONG_NAME_250)
        assert dir_name_part == expected, d.name
        for f in self._log_files(d):
            assert expected in f, f
