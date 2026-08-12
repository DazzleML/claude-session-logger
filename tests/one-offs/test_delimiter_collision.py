"""Delimiter-collision regression tests (session names / shell types containing `__`).

Live repro (2026-08-12, Linux box `oarsapps`): session named
`2026-8-12__zeromeld.org__reddit-slack-fixes` running inside tmux session
`redditslack_2026-08-12_updating-users` caused the rename/reconcile machinery
to fire 45 times, each pass PREPENDING another `{shell}__{first-name-segment}__`
layer into log filenames (insertion, not replacement):

    FROM: .sesslog_tmux_redditslack_2026-08-12_updating-users__2026-8-12__zeromeld.org__reddit-slack-fixes__{guid}_dev.log
    TO:   .sesslog_tmux_redditslack_2026-08-12_updating-users__2026-8-12__tmux_redditslack_2026-08-12_updating-users__2026-8-12__zeromeld.org__reddit-slack-fixes__{guid}_dev.log

Root causes under test:
  R1  sanitize/naming never neutralizes the format's own `__` delimiter,
      so it can appear inside the {shell} and {name} filename fields.
  R2  Truncating parses `__([^_]+?)(?:--\\d{3})?__{guid}` return a plausible
      WRONG name (the last no-underscore segment) instead of failing:
        - reconciliation.extract_session_name_from_file
        - file_io._embedded_session_name  (feeds the orphan sweep!)
  R3  shell_type embeds the tmux session name verbatim (user-controlled).
  R4  The named->renamed branch has no idempotency guard, so a mis-parsed
      old/new pair becomes a filename-growth feedback loop.
  R5  The unnamed->named branch's `[\\w.]+` shell field rejects hyphens,
      silently skipping files whose shell contains `-` (e.g. dates).

These tests are written RED-FIRST against f650334 (v0.3.7-pre): each test
asserts the *correct* contract and is expected to FAIL before the fix.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Live repro values -- do not "clean up"; they are the actual bug inputs.
GUID = "8f360aa8-146b-4a99-9438-053c28f52095"
LIVE_SHELL = "tmux_redditslack_2026-08-12_updating-users"
LIVE_NAME = "2026-8-12__zeromeld.org__reddit-slack-fixes"
USER = "dev"

# What the name should collapse to once `__` is banned from filename fields.
COLLAPSED_NAME = "2026-8-12_zeromeld.org_reddit-slack-fixes"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_SCRIPT = REPO_ROOT / "hooks" / "scripts" / "log-command.py"


def correct_filename(channel: str = "sesslog", name: str = LIVE_NAME,
                     shell: str = LIVE_SHELL) -> str:
    return f".{channel}_{shell}__{name}__{GUID}_{USER}.log"


# ============================================================================
# R2 -- truncating parses must return the FULL embedded name
# ============================================================================

class TestNameExtraction:
    def test_extract_session_name_from_file_returns_full_name(self):
        from cclogger.reconciliation import extract_session_name_from_file
        got = extract_session_name_from_file(Path(correct_filename()), GUID)
        assert got == LIVE_NAME, (
            f"truncating parse: got {got!r} -- this wrong-but-plausible name "
            f"is what feeds the rename feedback loop"
        )

    def test_extract_session_name_with_sequence_suffix(self):
        from cclogger.reconciliation import extract_session_name_from_file
        fname = f".sesslog_{LIVE_SHELL}__{LIVE_NAME}--007__{GUID}_{USER}.log"
        got = extract_session_name_from_file(Path(fname), GUID)
        assert got == LIVE_NAME

    def test_embedded_session_name_returns_full_name(self):
        """file_io._embedded_session_name feeds sweep_orphan_session_name_files.
        A truncated parse here makes the sweep classify CORRECT files as
        orphans and quarantine them into baks/."""
        from cclogger.file_io import _embedded_session_name
        # Use an underscore-free shell so the (separately broken) shell field
        # matches and we isolate the name-parse defect.
        fname = correct_filename(shell="bash")
        got = _embedded_session_name(fname, GUID)
        assert got == LIVE_NAME, f"sweep would treat correct file as orphan (got {got!r})"

    def test_embedded_session_name_tolerates_hyphenated_shell(self):
        """R5 variant: the shell-bits field must accept hyphens (dates in
        tmux names). With `[\\w.]+` the live filenames never match at all."""
        from cclogger.file_io import _embedded_session_name
        got = _embedded_session_name(correct_filename(), GUID)
        assert got == LIVE_NAME


# ============================================================================
# R4 -- rename must be idempotent (no insertion when target already present)
# ============================================================================

class TestRenameIdempotency:
    def test_rename_noop_when_new_name_already_embedded(self, tmp_path):
        """The live amplifier: old=truncated-suffix, new=full name.
        The correctly-named file already contains __{new}__{guid}; the rename
        pass must leave it alone instead of substituting old->new INSIDE it."""
        from cclogger.reconciliation import _rename_files_for_session_change
        f = tmp_path / correct_filename()
        f.write_text("payload")

        _rename_files_for_session_change(
            tmp_path,
            old_session_name="reddit-slack-fixes",   # what the truncating parse returned
            new_session_name=LIVE_NAME,
            session_id=GUID,
        )

        assert f.exists(), (
            "correctly-named file was renamed away: "
            + ", ".join(p.name for p in tmp_path.iterdir())
        )
        assert len(list(tmp_path.iterdir())) == 1

    def test_rename_applies_clean_transition(self, tmp_path):
        """Sanity: a legitimate rename (old name genuinely embedded) still works."""
        from cclogger.reconciliation import _rename_files_for_session_change
        old = tmp_path / f".sesslog_bash__oldname__{GUID}_{USER}.log"
        old.write_text("payload")

        _rename_files_for_session_change(
            tmp_path, old_session_name="oldname",
            new_session_name="newname", session_id=GUID,
        )

        assert (tmp_path / f".sesslog_bash__newname__{GUID}_{USER}.log").exists()
        assert not old.exists()

    def test_unnamed_to_named_with_hyphenated_shell(self, tmp_path):
        """R5: unnamed->named must handle shells containing hyphens."""
        from cclogger.reconciliation import _rename_files_for_session_change
        unnamed = tmp_path / f".sesslog_{LIVE_SHELL}_{GUID}_{USER}.log"
        unnamed.write_text("payload")

        _rename_files_for_session_change(
            tmp_path, old_session_name=None,
            new_session_name="somename", session_id=GUID,
        )

        expected = tmp_path / f".sesslog_{LIVE_SHELL}__somename__{GUID}_{USER}.log"
        assert expected.exists(), (
            "unnamed file with hyphenated shell was silently skipped: "
            + ", ".join(p.name for p in tmp_path.iterdir())
        )


# ============================================================================
# R1/R3 -- the delimiter must be unrepresentable inside filename fields
# ============================================================================

class TestDelimiterSanitization:
    def test_sanitize_dirname_collapses_double_underscore(self):
        from cclogger.session_naming import sanitize_dirname
        assert "__" not in sanitize_dirname(LIVE_NAME)

    def test_sanitize_dirname_preserves_single_underscores(self):
        from cclogger.session_naming import sanitize_dirname
        assert sanitize_dirname("a_b_c") == "a_b_c"

    def test_get_session_name_returns_collapsed_name(self, tmp_path, monkeypatch):
        """The name-cache may hold a raw `__` name (written by /rename);
        the logger-facing accessor must return the collapsed form so every
        downstream filename consumer is safe by construction."""
        monkeypatch.setenv("CLAUDE_DIR", str(tmp_path))
        state_dir = tmp_path / "session-states"
        state_dir.mkdir()
        (state_dir / f"{GUID}.name-cache").write_text(LIVE_NAME, encoding="utf-8")

        from cclogger.session_naming import get_session_name
        got = get_session_name(GUID, str(tmp_path / "transcript.jsonl"))
        assert got == COLLAPSED_NAME

    def test_shell_type_collapses_tmux_delimiter(self, monkeypatch):
        """tmux session names are user-controlled free text and may contain
        `__`; shell_type must collapse it before filename embedding."""
        import cclogger.session_state as ss
        monkeypatch.setattr(ss, "detect_tmux_session", lambda: "proj__topic__extra")
        info = ss.ToolInfo(
            name="Bash", input={}, description="",
            session_id=GUID, transcript_path="/tmp/nonexistent-transcript.jsonl",
            raw_json={},
        )
        ctx = ss.build_session_context(info)
        assert "__" not in ctx.shell_type, ctx.shell_type


# ============================================================================
# End-to-end: real hook subprocess, filenames must be STABLE
# ============================================================================

def _drive_hook(home: Path, events: list, env_extra: dict | None = None) -> None:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["USERNAME"] = USER
    env["USER"] = USER
    env.pop("CLAUDE_DIR", None)
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.pop("TMUX", None)  # deterministic non-tmux shell detection
    # Hook subprocess must see user-site packages despite redirected HOME
    site = str(Path.home() / ".local" / "lib" /
               f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")
    env["PYTHONPATH"] = site + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
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
            tool_input={"command": f"echo step-{i}"},
            tool_response={"stdout": f"step-{i}", "stderr": "", "interrupted": False},
        ))
    return evs


class TestEndToEndFilenameStability:
    @pytest.fixture
    def scratch_home(self, tmp_path):
        home = tmp_path / "home"
        state = home / ".claude" / "session-states"
        state.mkdir(parents=True)
        # Seed the live session name exactly as /rename left it on the real box
        (state / f"{GUID}.name-cache").write_text(LIVE_NAME, encoding="utf-8")
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

    def test_filenames_stable_across_events_and_runs(self, scratch_home):
        """THE live-repro gate. Two full runs (SessionStart + tools each);
        the set of log filenames must be identical after run 1 and run 2,
        one file per channel, shell string appearing exactly once per name."""
        home, transcript = scratch_home

        _drive_hook(home, _events(transcript))
        dirs = self._session_dirs(home)
        assert len(dirs) == 1, [d.name for d in dirs]
        after_run1 = self._log_files(dirs[0])

        _drive_hook(home, _events(transcript))  # second run = restart
        dirs = self._session_dirs(home)
        assert len(dirs) == 1, [d.name for d in dirs]
        after_run2 = self._log_files(dirs[0])

        assert after_run1 == after_run2, (
            "filename set changed between runs (growth loop):\n run1=%s\n run2=%s"
            % (after_run1, after_run2))

        # one file per channel, no --NNN sequence fragments
        chans = [n.split("_")[0] for n in after_run1]
        assert len(chans) == len(set(chans)), f"duplicate channel files: {after_run1}"
        assert not any("--0" in n for n in after_run1), after_run1

    def test_filenames_use_collapsed_name(self, scratch_home):
        """New files must embed the collapsed (delimiter-free) name."""
        home, transcript = scratch_home
        _drive_hook(home, _events(transcript, n_tools=1))
        dirs = self._session_dirs(home)
        assert len(dirs) == 1
        assert COLLAPSED_NAME in dirs[0].name and LIVE_NAME not in dirs[0].name, dirs[0].name
        for n in self._log_files(dirs[0]):
            assert LIVE_NAME not in n, n
            assert COLLAPSED_NAME in n, n


# ============================================================================
# Subtype-derived channel basenames: third `_`-bearing field (adversarial
# tester Finding 1 -- snake_case subagent types re-triggered the loop)
# ============================================================================

class TestSubtypeBasenames:
    def test_get_subtype_never_emits_underscores(self):
        """Subtypes join channel basenames (`.agents-{subtype}_...`); the
        filename parses assume basenames are `_`-free. snake_case subagent
        types and the sanitizer's own replacement char must both come out
        hyphenated."""
        from cclogger.categorize import get_subtype
        got = get_subtype("meta", "Agent",
                          {"tool_input": {"subagent_type": "my_snake_agent"}})
        if got is not None:
            assert "_" not in got, got
        got2 = get_subtype("meta", "Agent",
                           {"tool_input": {"subagent_type": "we ird/type"}})
        if got2 is not None:
            assert "_" not in got2, got2

    def test_agents_channel_stable_with_snake_case_subagent(self, tmp_path):
        """E2E: Agent events with a snake_case subagent_type must not cause
        filename proliferation (tester repro: 10->13->16->19 files, one new
        `--NNN` per hook event via phantom basename `agents-my`)."""
        home = tmp_path / "home"
        state = home / ".claude" / "session-states"
        state.mkdir(parents=True)
        (state / f"{GUID}.name-cache").write_text("normal-name", encoding="utf-8")
        transcript = home / ".claude" / "projects" / "-" / f"{GUID}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps({"type": "user", "message":
                              {"role": "user", "content": "hi"}}) + "\n")

        base = {"session_id": GUID, "transcript_path": str(transcript),
                "cwd": "/", "permission_mode": "default"}
        events = [dict(base, hook_event_name="SessionStart", source="startup")] + [
            dict(base, hook_event_name="PostToolUse", tool_name="Agent",
                 tool_input={"subagent_type": "my_snake_agent",
                             "prompt": f"task {i}", "description": "t"},
                 tool_response={"result": "ok"})
            for i in range(3)]

        counts = []
        for _ in range(3):  # three restart passes
            _drive_hook(home, events)
            dirs = [p for p in (home / ".claude" / "sesslogs").iterdir()
                    if p.is_dir()]
            assert len(dirs) == 1, [x.name for x in dirs]
            names = sorted(f.name for f in dirs[0].iterdir()
                           if f.is_file() and GUID in f.name)
            counts.append(len(names))
            for n in names:
                assert "--0" not in n, f"sequence fragment appeared: {n}"

        assert counts[0] == counts[1] == counts[2], (
            f"file count grew across restarts: {counts}")
