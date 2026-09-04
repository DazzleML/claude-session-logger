"""Unit 5 of the sidechain-capture design (2026-09-03): two hook subscriptions
and what they write.

* `PostToolUseFailure` (#57): a failed tool call is logged through the same
  routes as a success, with a one-line `[FAILED: reason]` marker INSIDE the
  frame at every verbosity; the reason is the first line of `tool_error`,
  capped. On the success path `tool_response.interrupted` and a non-zero
  `exit_code` mark too. Successes are byte-identical to before.
  `is_failure` is a collect/exclude attribute.
* `SubagentStart`: the `{AGENT-START:explore ...}` kickoff line (leg
  dispatch); `SubagentStop` closes a typed agent's block with
  `{AGENT-STOP:explore ...}` (leg report). Untyped forks get no brackets
  (maintainer decision, Addendum 6).

Design: 2026-09-03__15-32-54__dev-workflow-process__sidechain-capture-thinking-and-sesslog-main.md; issue #57.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO / "hooks" / "scripts" / "log-command.py"
GUID = "fa11a9e1-0903-4bbb-8ccc-0000000000e5"
USER = "failuser"
TS = datetime(2026, 9, 3, 21, 20, 0)
STAMP = "[[2026-09-03 21:20:00]]"


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


@pytest.fixture
def cursors(tmp_path, monkeypatch):
    d = tmp_path / "states"
    d.mkdir()
    monkeypatch.setattr("cclogger.conversation._agent_cursor_path", lambda sid, aid: d / f"{sid}.agent-{aid}.cursor")
    monkeypatch.setattr("cclogger.conversation._convo_cursor_path", lambda sid: d / f"{sid}.convo-cursor")
    return d


def _ctx():
    from cclogger.models import SessionContext
    return SessionContext(shell_type="bash.exe", session_name="fail-unit", session_id=GUID, username=USER)


def _sessdir(home: Path) -> Path:
    dirs = list((home / ".claude" / "sesslogs").glob("*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def _read(d: Path, glob: str) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in d.glob(glob))


def _entry(payload: dict, config=None):
    """generate_entry through the same path log-command.py uses."""
    from cclogger.formatters import get_command_content_structured
    from cclogger.formatters.legacy import generate_entry
    from cclogger.models import Config, ToolInfo
    cfg = config or Config()
    info = ToolInfo.from_json(payload)
    cc = get_command_content_structured(info, cfg)
    return generate_entry(info, cfg, cc, TS), info, cfg


def _fail(tool: str, tool_input: dict, error: str = "boom", **extra) -> dict:
    return {"session_id": GUID, "transcript_path": "", "cwd": "/", "permission_mode": "default",
            "hook_event_name": "PostToolUseFailure", "tool_name": tool, "tool_input": tool_input,
            "tool_use_id": "toolu_1", "tool_error": error, **extra}


def _ok(tool: str, tool_input: dict, response: dict, **extra) -> dict:
    return {"session_id": GUID, "transcript_path": "", "cwd": "/", "permission_mode": "default",
            "hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": tool_input,
            "tool_use_id": "toolu_1", "tool_response": response, **extra}


# ============================================================================
# The reason
# ============================================================================

class TestFailureReason:
    def _r(self, payload):
        from cclogger.formatters.legacy import failure_reason_from_payload
        return failure_reason_from_payload(payload)

    def test_first_nonblank_line_of_tool_error_capped(self):
        long = "x" * 300
        assert self._r(_fail("Edit", {}, error="\n\nString to replace not found in file.\nString: a")) == \
            "String to replace not found in file."
        assert self._r(_fail("Edit", {}, error=long)) == "x" * 120

    def test_dict_error_and_empty_error(self):
        assert self._r(_fail("Edit", {}, error={"message": "denied"})) == "denied"
        assert self._r(_fail("Edit", {}, error="")) == "failed"
        assert self._r(_fail("Edit", {}, error=None)) == "failed"

    def test_dict_error_prefers_message_then_error_then_compact_json(self):
        """Kills N1 (key precedence) and N2 (compact JSON, not a Python repr)."""
        assert self._r(_fail("Edit", {}, error={"message": "m", "error": "e"})) == "m"
        assert self._r(_fail("Edit", {}, error={"error": "e"})) == "e"
        assert self._r(_fail("Edit", {}, error={"code": 5, "detail": "x"})) == '{"code":5,"detail":"x"}'

    def test_non_string_error_is_stringified_not_fatal(self):
        """Kills N5: a numeric or list tool_error must not raise inside the hook."""
        assert self._r(_fail("Edit", {}, error=42)) == "42"
        assert self._r(_fail("Edit", {}, error=["a", "b"])) == "['a', 'b']"

    def test_negative_exit_code_is_a_failure(self):
        """Kills M1: a signal-killed process reports a negative code."""
        assert self._r(_ok("Bash", {}, {"exit_code": -9})) == "exit -9"

    def test_only_the_literal_true_means_interrupted(self):
        """Kills M2: truthy strings or ints are not the flag."""
        for v in ("yes", 1, {"x": 1}, [1]):
            assert self._r(_ok("Bash", {}, {"interrupted": v})) is None, v

    def test_success_path_marks_interrupted_and_nonzero_exit_only(self):
        assert self._r(_ok("Bash", {}, {"stdout": "", "stderr": "", "interrupted": True})) == "interrupted"
        assert self._r(_ok("Bash", {}, {"stdout": "", "stderr": "warn", "exit_code": 2})) == "exit 2"
        assert self._r(_ok("Bash", {}, {"stdout": "", "stderr": "warn", "exit_code": 0})) is None
        assert self._r(_ok("Bash", {}, {"stdout": "", "stderr": "", "interrupted": False})) is None
        assert self._r(_ok("Bash", {}, {"exit_code": True})) is None  # a bool is not an exit code
        assert self._r(_ok("Read", {}, "not a dict")) is None
        assert self._r({}) is None and self._r("junk") is None


# ============================================================================
# The marker, at every verbosity, in every channel
# ============================================================================

class TestMarker:
    def test_failed_edit_carries_reason_inside_the_frame(self):
        e, _, _ = _entry(_fail("Edit", {"file_path": "C:/x.py", "old_string": "a", "new_string": "b"},
                               error="String to replace not found in file."))
        assert e.is_failure and e.failure_reason == "String to replace not found in file."
        legacy = e.metadata["_legacy_complete"]
        assert legacy.endswith("[FAILED: String to replace not found in file.] }")
        assert e.summary.endswith("[FAILED: String to replace not found in file.]")

    def test_success_is_unmarked(self):
        e, _, _ = _entry(_ok("Edit", {"file_path": "C:/x.py", "old_string": "a", "new_string": "b"}, {"ok": True}))
        assert not e.is_failure and e.failure_reason is None
        assert "FAILED" not in e.metadata["_legacy_complete"] and "FAILED" not in (e.summary or "")

    @pytest.mark.parametrize("verbosity", [0, 1, 2, 3, 4])
    def test_one_line_at_every_global_verbosity(self, verbosity):
        from cclogger.models import Config
        cfg = Config()
        cfg.verbosity = verbosity
        e, _, _ = _entry(_fail("Read", {"file_path": "C:/missing.md"}, error="File does not exist."), config=cfg)
        legacy = e.metadata["_legacy_complete"]
        assert "\n" not in legacy
        assert "[FAILED: File does not exist.]" in legacy

    def test_action_only_still_marks(self):
        from cclogger.models import Config
        cfg = Config()
        cfg.action_only["bash"] = True
        e, _, _ = _entry(_fail("Bash", {"command": "false"}, error="Command failed with exit code 1"), config=cfg)
        assert e.metadata["_legacy_complete"].endswith("{Bash [FAILED: Command failed with exit code 1] }")

    def test_marker_survives_channel_formatting_and_frame_padding(self):
        from cclogger.formatters import format_for_channel
        from cclogger.frame import frame_is_matched
        from cclogger.models import ChannelOptions
        e, _, _ = _entry(_fail("Bash", {"command": 'echo "{"'}, error="unexpected EOF while looking for matching `\"'"))
        for opts, ch in ((None, "shell"), (ChannelOptions(verbosity={"max_chars": 100}), "tools"), (ChannelOptions(), "sesslog")):
            out = format_for_channel(e, opts, ch)
            assert "[FAILED: unexpected EOF" in out and "\n" not in out, out
            assert frame_is_matched(out), out

    def test_marker_on_a_template_tool_at_preview_verbosity(self):
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions
        e, _, _ = _entry(_fail("Write", {"file_path": "C:/w.txt", "content": "line\n" * 50}, error="EACCES: permission denied"))
        out = format_for_channel(e, ChannelOptions(verbosity={"max_chars": 20}), "tools")
        assert out.endswith("[FAILED: EACCES: permission denied] }") and "\n" not in out

    def test_marker_survives_agent_label_never_on_the_plain_summary(self):
        """Kills M6: under agent_label "never" the formatter takes the plain
        (context-free) summary, which must carry the marker too."""
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions
        e, _, _ = _entry(_fail("Write", {"file_path": "C:/w.txt", "content": "x"}, error="EACCES",
                               agent_id="a0000000000000e5", agent_type="Explore"))
        out = format_for_channel(e, ChannelOptions(verbosity="full", agent_label="never"), "tools")
        assert "[FAILED: EACCES]" in out and "|" not in out.split("{", 1)[1].split(":", 1)[0]

    def test_marker_on_the_plain_legacy_line_for_a_templateless_tool(self):
        """Kills N6: a Bash failure inside an agent under agent_label "never"
        renders from the plain legacy line, which must carry the marker."""
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions
        e, _, _ = _entry(_fail("Bash", {"command": "false"}, error="Command failed with exit code 1",
                               agent_id="a0000000000000e5", agent_type="Explore"))
        out = format_for_channel(e, ChannelOptions(agent_label="never"), "shell")
        assert out.endswith("[FAILED: Command failed with exit code 1] }") and "|" not in out

    @pytest.mark.parametrize("tool,tool_input", [
        ("Read", {"file_path": "C:/missing.md"}),
        ("Edit", {"file_path": "C:/x.py", "old_string": "a", "new_string": "b"}),
        ("Write", {"file_path": "C:/w.txt", "content": "x"}),
        ("MultiEdit", {"file_path": "C:/x.py", "edits": [{"old_string": "a", "new_string": "b"}]}),
        ("NotebookEdit", {"notebook_path": "C:/n.ipynb", "new_source": "print(1)"}),
        ("Grep", {"pattern": "needle"}),
        ("Glob", {"pattern": "**/*.py"}),
        ("PowerShell", {"command": "Get-Process nope"}),
        ("Bash", {"command": "false"}),
    ])
    @pytest.mark.parametrize("channel", ["sesslog", "tools", "shell"])
    def test_every_named_tool_marks_in_every_named_channel(self, tool, tool_input, channel):
        """#57 criterion 1, stated as the issue states it: the named tools all
        render the marker in .sesslog_*, .tools_* and .shell_*, and their
        successful counterparts stay unmarked. The marker is composed once, at
        the entry generator, so this is a coverage pin rather than nine code
        paths -- which is exactly what makes it worth pinning: a later change
        that special-cased one tool would show up here."""
        from cclogger.formatters import format_for_channel
        from cclogger.frame import frame_is_matched
        from cclogger.models import ChannelOptions
        failed, _, _ = _entry(_fail(tool, tool_input, error="it did not work"))
        out = format_for_channel(failed, ChannelOptions(), channel)
        assert "[FAILED: it did not work]" in out, (tool, channel, out)
        assert "\n" not in out and frame_is_matched(out), out

        ok, _, _ = _entry(_ok(tool, tool_input, {"stdout": "", "stderr": "", "interrupted": False}))
        assert "FAILED" not in format_for_channel(ok, ChannelOptions(), channel)

    def test_bash_nonzero_exit_marks_on_the_success_path(self):
        """#57 criterion 2: a Bash command that ran and exited non-zero arrives
        on PostToolUse, not PostToolUseFailure, and must still be marked."""
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions
        e, _, _ = _entry(_ok("Bash", {"command": "pytest tests/"},
                             {"stdout": "1 failed", "stderr": "", "exit_code": 1, "interrupted": False}))
        assert e.is_failure and e.failure_reason == "exit 1"
        for channel in ("sesslog", "tools", "shell"):
            assert "[FAILED: exit 1]" in format_for_channel(e, ChannelOptions(), channel), channel

    def test_agent_internal_failure_keeps_identity_and_marker(self):
        e, _, _ = _entry(_fail("Grep", {"pattern": "x"}, error="ripgrep exited 2",
                               agent_id="a0000000000000e5", agent_type="Explore"))
        legacy = e.metadata["_legacy_complete"]
        assert "{Grep|Explore: " in legacy and legacy.endswith("[FAILED: ripgrep exited 2] }")
        assert e.agent_leg == "internal" and e.is_failure


# ============================================================================
# is_failure as a collect / exclude attribute
# ============================================================================

class TestFailureAttribute:
    def test_whitelisted(self):
        from cclogger.models import COLLECT_RECOGNIZED_KEYS, EXCLUDE_RECOGNIZED_KEYS
        assert "is_failure" in COLLECT_RECOGNIZED_KEYS and "is_failure" in EXCLUDE_RECOGNIZED_KEYS

    def test_failures_only_channel(self, isolated_home):
        from cclogger.logger import SessionLogger
        from cclogger.models import ChannelConfig, ChannelOptions, Config
        cfg = Config()
        cfg.routing.channels["failures"] = ChannelConfig(file_prefix=".failures_",
                                                          options=ChannelOptions(collect={"is_failure": True}))
        logger = SessionLogger(cfg, _ctx(), TS)
        for payload in (_fail("Read", {"file_path": "C:/nope"}, error="File does not exist."),
                        _ok("Read", {"file_path": "C:/yes"}, {"file": {"content": "x"}})):
            e, info, _ = _entry(payload, config=cfg)
            logger.log_entry(e, info.name, "system", event_time=TS, raw_json=info.raw_json)
        d = _sessdir(isolated_home)
        failures = _read(d, ".failures_*")
        assert "C:/nope" in failures and "[FAILED:" in failures and "C:/yes" not in failures
        assert "C:/yes" in _read(d, ".sesslog_*")

    def test_exclude_failures_from_a_channel(self, isolated_home):
        from cclogger.logger import SessionLogger
        from cclogger.models import Config
        cfg = Config()
        cfg.routing.channels["tools"].options.exclude = {"is_failure": True}
        logger = SessionLogger(cfg, _ctx(), TS)
        e, info, _ = _entry(_fail("Read", {"file_path": "C:/nope"}, error="File does not exist."), config=cfg)
        logger.log_entry(e, info.name, "system", event_time=TS, raw_json=info.raw_json)
        d = _sessdir(isolated_home)
        assert "C:/nope" not in _read(d, ".tools_*") and "C:/nope" in _read(d, ".sesslog_*")


# ============================================================================
# Brackets
# ============================================================================

def _run(event, config=None):
    from cclogger.conversation import handle_conversation_event
    from cclogger.models import Config
    handle_conversation_event(event["hook_event_name"], event, _ctx(), config or Config(), TS)


def _start(agent_type="Explore", agent_id="a0000000000000e5", **extra) -> dict:
    return {"session_id": GUID, "transcript_path": "", "cwd": "/", "permission_mode": "default",
            "hook_event_name": "SubagentStart", "agent_id": agent_id, "agent_type": agent_type, **extra}


def _stop(agent_type="Explore", agent_id="a0000000000000e5", last="REPORT", side="") -> dict:
    return {"session_id": GUID, "transcript_path": "", "cwd": "/", "permission_mode": "default",
            "hook_event_name": "SubagentStop", "agent_id": agent_id, "agent_type": agent_type,
            "stop_hook_active": False, "agent_transcript_path": side, "last_assistant_message": last}


class TestBrackets:
    def test_start_line_with_description_when_present(self, isolated_home, cursors):
        _run(_start(description="search the docs"))
        d = _sessdir(isolated_home)
        assert f"{STAMP} {{AGENT-START:explore: search the docs }}" in _read(d, ".agents-explore_*")
        assert "{AGENT-START:explore:\nsearch the docs\n}" in _read(d, ".convo_*")

    def test_multi_line_description_uses_its_first_line(self, isolated_home, cursors):
        """Kills M9."""
        _run(_start(description="  first line of the brief\nsecond line\nthird"))
        assert "{AGENT-START:explore: first line of the brief }" in _read(_sessdir(isolated_home), ".sesslog_*")

    def test_stop_line_counts_narration_and_thinking_separately(self, isolated_home, cursors, tmp_path):
        """Kills M11: with a sidechain of one thought, one narration and the
        report, the closing line says 1 narration, 1 thinking."""
        side = tmp_path / "agent.jsonl"
        entries = [
            {"type": "assistant", "timestamp": "2026-09-04T01:20:00.000Z", "message": {"content": [
                {"type": "thinking", "thinking": "think first", "signature": "s"},
                {"type": "text", "text": "narrate"}]}},
            {"type": "assistant", "timestamp": "2026-09-04T01:20:05.000Z", "message": {"content": [
                {"type": "text", "text": "REPORT"}]}},
        ]
        side.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        _run(_start())
        _run(_stop(side=str(side)))
        assert "{AGENT-STOP:explore: stopped (1 narration, 1 thinking, report) }" in _read(_sessdir(isolated_home), ".agents-explore_*")

    def test_description_wins_over_prompt(self, isolated_home, cursors):
        """Kills N7: when both are present the short description is the
        kickoff line, not the (long) prompt."""
        _run(_start(description="brief", prompt="a very long prompt\nwith lines"))
        assert "{AGENT-START:explore: brief }" in _read(_sessdir(isolated_home), ".sesslog_*")

    def test_start_line_without_description(self, isolated_home, cursors):
        _run(_start())
        assert f"{STAMP} {{AGENT-START:explore: started }}" in _read(_sessdir(isolated_home), ".sesslog_*")

    def test_stop_closes_the_block_after_the_report(self, isolated_home, cursors):
        _run(_start())
        _run(_stop())
        per_agent = _read(_sessdir(isolated_home), ".agents-explore_*")
        want = ["{AGENT-START:explore: started }", "{AGENT:explore: REPORT }",
                "{AGENT-STOP:explore: stopped (0 narration, 0 thinking, report) }"]
        pos = [per_agent.find(w) for w in want]
        assert all(p >= 0 for p in pos), per_agent
        assert pos == sorted(pos)

    def test_bracket_legs(self, isolated_home, cursors, monkeypatch):
        import cclogger.conversation as conv
        seen = []
        real = conv.SessionLogger.log_entry
        monkeypatch.setattr(conv.SessionLogger, "log_entry",
                            lambda self, entry, **kw: (seen.append((entry.role, entry.agent_leg)), real(self, entry, **kw)))
        _run(_start())
        _run(_stop())
        assert seen == [("agent-start", "dispatch"), ("agent", "report"), ("agent-stop", "report")]

    def test_untyped_forks_get_no_brackets(self, isolated_home, cursors, monkeypatch):
        import cclogger.conversation as conv
        seen = []
        real = conv.SessionLogger.log_entry
        monkeypatch.setattr(conv.SessionLogger, "log_entry",
                            lambda self, entry, **kw: (seen.append(entry.role), real(self, entry, **kw)))
        _run(_start(agent_type="", agent_id="a00000000000beef"))
        _run(_stop(agent_type="", agent_id="a00000000000beef", last="fork line"))
        assert seen == ["agent"]
        d = _sessdir(isolated_home)
        feed = _read(d, ".agents-untyped_*")
        assert feed.count("[[") == 1 and "AGENT-START" not in feed and "AGENT-STOP" not in feed

    def test_start_without_agent_id_is_ignored(self, isolated_home, cursors):
        _run({"session_id": GUID, "transcript_path": "", "hook_event_name": "SubagentStart", "agent_type": "Explore"})
        assert not list((isolated_home / ".claude" / "sesslogs").glob("*/.agents-*"))

    def test_brackets_carry_identity_under_id_label_mode_and_survive_agent_label_never(self):
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions, LogEntry
        e = LogEntry(raw_content="started", role="agent-start", timestamp=TS, tool_name="SubagentStart",
                     agent_context="oracle", agent_id="a1", agent_leg="dispatch")
        assert format_for_channel(e, ChannelOptions(), "sesslog") == f"{STAMP} {{AGENT-START:oracle: started }}"
        assert format_for_channel(e, ChannelOptions(agent_label="never"), "sesslog") == f"{STAMP} {{AGENT-START: started }}"


# ============================================================================
# hooks.json and the end-to-end path
# ============================================================================

class TestSubscriptions:
    def test_hooks_json_subscribes_both_events(self):
        hooks = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        for ev in ("PostToolUseFailure", "SubagentStart"):
            assert ev in hooks, ev
            assert hooks[ev][0]["hooks"][0]["command"].endswith("run-hook.mjs")


def _drive_hook(home: Path, events: list) -> None:
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
    for ev in events:
        proc = subprocess.run([sys.executable, str(HOOK_SCRIPT)], input=json.dumps(ev).encode("utf-8"),
                              capture_output=True, env=env, timeout=30)
        assert proc.returncode == 0, proc.stderr.decode()[:800]


class TestEndToEnd:
    def test_failure_and_brackets_through_the_real_hook(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        main = tmp_path / "main.jsonl"
        main.write_text("", encoding="utf-8")
        base = {"session_id": GUID, "transcript_path": str(main), "cwd": "/", "permission_mode": "default"}
        events = [
            dict(base, hook_event_name="PostToolUseFailure", tool_name="Read",
                 tool_input={"file_path": "C:/missing.md"}, tool_use_id="t1", tool_error="File does not exist."),
            dict(base, hook_event_name="PostToolUse", tool_name="Read",
                 tool_input={"file_path": "C:/present.md"}, tool_use_id="t2", tool_response={"file": {"content": "x"}}),
            dict(base, hook_event_name="SubagentStart", agent_id="a0000000000000e5", agent_type="Explore"),
            dict(base, hook_event_name="SubagentStop", agent_id="a0000000000000e5", agent_type="Explore",
                 stop_hook_active=False, agent_transcript_path=str(tmp_path / "none.jsonl"),
                 last_assistant_message="E2E REPORT"),
        ]
        _drive_hook(home, events)
        d = list((home / ".claude" / "sesslogs").glob("*"))[0]
        import re
        sesslog = _read(d, ".sesslog_*")
        assert re.search(r"^\[\[[^\]]+\]\] \{Read: .*missing\.md.* \[FAILED: File does not exist\.\] \}$", sesslog, re.M), sesslog
        present = [l for l in sesslog.splitlines() if "present.md" in l]
        assert len(present) == 1 and "FAILED" not in present[0]
        per_agent = _read(d, ".agents-explore_*")
        assert per_agent.find("AGENT-START") < per_agent.find("E2E REPORT") < per_agent.find("AGENT-STOP")
