"""Unit 2 of the sidechain-capture design (2026-09-03): the SubagentStop
handler reads the agent's OWN transcript (`agent_transcript_path`) through a
per-agent cursor and emits its narration and thinking as internal legs with
their own timestamps, then its final text as the report. The main transcript
is never read on SubagentStop -- that read, from the cursor shared with
Stop, is what labeled main-thread narration as an agent's report and dropped
the agent's own (the report-leg bug).

Ground truth this pins (measured 2026-09-03): the main transcript holds no
agent turns (0 `isSidechain` entries in 3,352); untyped forks have no
sidechain at all (0 of 709 on the box); a sidechain is complete before the
parent hears the agent finished (7/7); thinking blocks are
`{"type": "thinking", "thinking": ..., "signature": ...}`.

Acceptance checks: AC-2 (last text == last_assistant_message, else a logged
mismatch and the payload wins), AC-3 (main-thread narration never under an
AGENT label; it stays for the next Stop), AC-4 (a resumed agent yields each
turn once), AC-5 (untyped fork: exactly the one line it produced before, no
warning), AC-6 (no duplicated tool calls), AC-13 (Config.thinking off
builds no thinking entry).

Design: 2026-09-03__15-32-54__dev-workflow-process__sidechain-capture-thinking-and-sesslog-main.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO / "hooks" / "scripts" / "log-command.py"
GUID = "51dec4a1-0903-4bbb-8ccc-0000000000e2"
USER = "sideuser"
TS = datetime(2026, 9, 3, 18, 40, 0)
AGENT = "a0000000000000e2"


def _utc(h, m, s) -> str:
    return f"2026-09-03T{h:02d}:{m:02d}:{s:02d}.000Z"


def _local(h, m, s) -> str:
    """What the log stamps: the entry's UTC time rendered in local time."""
    dt = datetime(2026, 9, 3, h, m, s, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _assistant(ts: str, *blocks) -> dict:
    return {"type": "assistant", "timestamp": ts, "isSidechain": True, "agentId": AGENT,
            "message": {"role": "assistant", "content": list(blocks)}}


def _text(t):
    return {"type": "text", "text": t}


def _think(t):
    return {"type": "thinking", "thinking": t, "signature": "opaque"}


def _tool(name="Bash"):
    return {"type": "tool_use", "id": "toolu_x", "name": name, "input": {"command": "echo hi"}}


def _user_result() -> dict:
    return {"type": "user", "timestamp": _utc(15, 0, 5), "isSidechain": True,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_x", "content": "hi"}]}}


SIDECHAIN = [
    _assistant(_utc(15, 0, 1), _think("plan the search"), _text("Starting the search."), _tool()),
    _user_result(),
    _assistant(_utc(15, 0, 10), _think("found it"), _text("Found two candidates.")),
    _assistant(_utc(15, 0, 20), _text("FINAL REPORT: two files.")),
]


def _write_jsonl(path: Path, entries) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


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
    monkeypatch.setattr("cclogger.conversation._agent_cursor_path",
                        lambda sid, aid: d / f"{sid}.agent-{aid}.cursor")
    monkeypatch.setattr("cclogger.conversation._convo_cursor_path",
                        lambda sid: d / f"{sid}.convo-cursor")
    return d


def _ctx():
    from cclogger.models import SessionContext
    return SessionContext(shell_type="bash.exe", session_name="side-unit", session_id=GUID, username=USER)


def _stop(side_path, last="FINAL REPORT: two files.", agent_type="Explore", agent_id=AGENT, transcript=""):
    d = {"session_id": GUID, "transcript_path": transcript, "cwd": "/", "permission_mode": "default",
         "hook_event_name": "SubagentStop", "agent_id": agent_id, "agent_type": agent_type,
         "stop_hook_active": False, "agent_transcript_path": str(side_path)}
    if last is not None:
        d["last_assistant_message"] = last
    return d


def _run(event, config=None, event_time=TS):
    from cclogger.conversation import handle_conversation_event
    from cclogger.models import Config
    handle_conversation_event(event["hook_event_name"], event, _ctx(), config or Config(), event_time)


def _sessdir(home: Path) -> Path:
    dirs = list((home / ".claude" / "sesslogs").glob("*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def _read(d: Path, glob: str) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in d.glob(glob))


# ============================================================================
# The reader
# ============================================================================

class TestBlockExtraction:
    def test_text_and_thinking_in_order_tools_skipped(self):
        from cclogger.conversation import _extract_blocks_from_assistant_entry as x
        e = _assistant(_utc(1, 0, 0), _think("t1"), _text("a"), _tool(), _think("t2"), _text("b"))
        assert x(e) == [("thinking", "t1"), ("text", "a"), ("thinking", "t2"), ("text", "b")]

    def test_blank_blocks_and_signature_ignored(self):
        """A thinking block with no text is not an entry -- and this is the
        shape a real subagent transcript uses. Measured 2026-09-04 across
        eight sidechain files on the dev box: every persisted thinking block
        carried `"thinking": ""` with only its signature, so an agent's
        reasoning is structurally present and textually absent. Recording an
        empty `{AGENT-THINK:...}` line for each would be noise that says
        nothing. See tests/one-offs/thinking/poc_sidechain_thinking_live.py."""
        from cclogger.conversation import _extract_blocks_from_assistant_entry as x
        e = _assistant(_utc(1, 0, 0), {"type": "thinking", "thinking": "  ", "signature": "s"}, _text(""), _text("x"))
        assert x(e) == [("text", "x")]
        live_shape = _assistant(_utc(1, 0, 0), {"type": "thinking", "thinking": "", "signature": "ErUBCkYIBxgCKk..."},
                                _text("the report"))
        assert x(live_shape) == [("text", "the report")]

    def test_entry_timestamp_is_local_naive(self):
        from cclogger.conversation import _entry_timestamp
        got = _entry_timestamp({"timestamp": _utc(15, 26, 32)})
        assert got == datetime(2026, 9, 3, 15, 26, 32, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        assert _entry_timestamp({}) is None and _entry_timestamp({"timestamp": "nope"}) is None

    def test_non_string_timestamp_is_none_not_an_error(self):
        """Kills N2: a numeric or dict timestamp must not raise past the parser."""
        from cclogger.conversation import _entry_timestamp
        for bad in (1725375992, 1.5, {"$date": "x"}, ["x"]):
            assert _entry_timestamp({"timestamp": bad}) is None, bad

    def test_odd_blocks_are_skipped_not_fatal(self):
        """Kills N4 (a bare string in the content list) and N5 (text that is
        not a string): both are skipped and the good blocks survive."""
        from cclogger.conversation import _extract_blocks_from_assistant_entry as x
        e = {"type": "assistant", "message": {"content": [
            "a bare string", {"type": "text", "text": None}, {"type": "text", "text": ["list"]},
            {"type": "thinking", "thinking": 42}, _text("kept"),
        ]}}
        assert x(e) == [("text", "kept")]

    def test_top_level_content_shape_still_read(self):
        """Kills N3: an entry with `content` at the top level (no message dict)."""
        from cclogger.conversation import _extract_blocks_from_assistant_entry as x
        assert x({"type": "assistant", "content": [_think("t"), _text("a")]}) == [("thinking", "t"), ("text", "a")]


class TestReadSidechain:
    def test_reads_narrative_in_order_with_times(self, tmp_path, cursors):
        from cclogger.conversation import _read_sidechain
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN)
        items = _read_sidechain(str(p), GUID, AGENT)
        assert [(k, t) for k, t, _ in items] == [
            ("thinking", "plan the search"), ("text", "Starting the search."),
            ("thinking", "found it"), ("text", "Found two candidates."),
            ("text", "FINAL REPORT: two files."),
        ]
        assert items[0][2] == datetime(2026, 9, 3, 15, 0, 1, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)

    def test_thinking_can_be_left_out(self, tmp_path, cursors):
        from cclogger.conversation import _read_sidechain
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN)
        assert [k for k, _, _ in _read_sidechain(str(p), GUID, AGENT, include_thinking=False)] == ["text"] * 3

    def test_cursor_is_per_agent_and_incremental(self, tmp_path, cursors):
        """AC-4: a resumed agent yields only its new turns; another agent's cursor is separate."""
        from cclogger.conversation import _read_sidechain
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN[:2])
        first = _read_sidechain(str(p), GUID, AGENT)
        assert [t for _, t, _ in first] == ["plan the search", "Starting the search."]
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(SIDECHAIN[2]) + "\n")
        second = _read_sidechain(str(p), GUID, AGENT)
        assert [t for _, t, _ in second] == ["found it", "Found two candidates."]
        assert _read_sidechain(str(p), GUID, AGENT) == []
        other = _read_sidechain(str(p), GUID, "a0000000000000ff")
        assert len(other) == 4  # a different agent id starts from zero

    def test_shrunk_file_resets(self, tmp_path, cursors):
        from cclogger.conversation import _read_sidechain, _write_agent_cursor
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN[:1])
        _write_agent_cursor(GUID, AGENT, 99999)
        assert [t for _, t, _ in _read_sidechain(str(p), GUID, AGENT)] == ["plan the search", "Starting the search."]

    def test_a_bad_timestamp_line_does_not_abort_the_read(self, tmp_path, cursors):
        """Kills N2 through the reader: one entry with a numeric timestamp
        still yields its blocks (stamped None -> event time) and the rest."""
        from cclogger.conversation import _read_sidechain
        p = tmp_path / "agent.jsonl"
        bad = dict(SIDECHAIN[0]); bad["timestamp"] = 1725375992
        _write_jsonl(p, [bad, SIDECHAIN[2]])
        items = _read_sidechain(str(p), GUID, AGENT)
        assert [t for _, t, _ in items] == ["plan the search", "Starting the search.", "found it", "Found two candidates."]
        assert items[0][2] is None and items[2][2] is not None

    def test_cursor_paths_differ_for_ids_that_differ_only_by_punctuation(self, tmp_path, monkeypatch):
        """Kills N1: the cursor is keyed by the agent id; ids that differ only
        in `-`/`_` must not share a file."""
        import cclogger.conversation as conv
        monkeypatch.setattr(conv.paths, "session_states", lambda: tmp_path)
        paths_ = {conv._agent_cursor_path(GUID, aid) for aid in ("agent-1", "agent_1", "agent1")}
        assert len(paths_) == 3

    def test_missing_empty_and_bad_inputs_are_silent(self, tmp_path, cursors, monkeypatch):
        import cclogger.conversation as conv
        logged = []
        monkeypatch.setattr(conv, "debug_log", lambda m: logged.append(m))
        assert conv._read_sidechain("", GUID, AGENT) == []
        assert conv._read_sidechain(str(tmp_path / "nope.jsonl"), GUID, AGENT) == []
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        assert conv._read_sidechain(str(empty), GUID, AGENT) == []
        assert conv._read_sidechain(str(tmp_path), GUID, "") == []
        assert logged == []


# ============================================================================
# The handler
# ============================================================================

class TestSubagentStopHandler:
    def test_per_agent_file_holds_thinking_narration_and_report_in_order_with_true_stamps(self, isolated_home, cursors, tmp_path):
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN)
        _run(_stop(p))
        d = _sessdir(isolated_home)
        per_agent = _read(d, ".agents-explore_*")
        want = [
            f"[[{_local(15, 0, 1)}]] {{AGENT-THINK:explore: plan the search }}",
            f"[[{_local(15, 0, 1)}]] {{AGENT:explore: Starting the search. }}",
            f"[[{_local(15, 0, 10)}]] {{AGENT-THINK:explore: found it }}",
            f"[[{_local(15, 0, 10)}]] {{AGENT:explore: Found two candidates. }}",
            f"[[{_local(15, 0, 20)}]] {{AGENT:explore: FINAL REPORT: two files. }}",
        ]
        pos = [per_agent.find(w) for w in want]
        assert all(x >= 0 for x in pos), (want, per_agent)
        assert pos == sorted(pos)
        # the identity shows under the default agent_label ("always"); the
        # same entries reach sesslog and convo
        sesslog = _read(d, ".sesslog_*")
        assert "{AGENT-THINK:explore: plan the search }" in sesslog
        assert "{AGENT:explore: FINAL REPORT: two files. }" in sesslog
        convo = _read(d, ".convo_*")
        assert "{AGENT-THINK:explore:\nplan the search\n}" in convo
        assert "{AGENT:explore:\nFINAL REPORT: two files.\n}" in convo

    def test_legs_are_stamped(self, isolated_home, cursors, tmp_path, monkeypatch):
        """internal vs report is what sesslog-main will exclude on."""
        import cclogger.conversation as conv
        seen = []
        real = conv.SessionLogger.log_entry
        monkeypatch.setattr(conv.SessionLogger, "log_entry",
                            lambda self, entry, **kw: (seen.append((entry.kind, entry.agent_leg, entry.raw_content)), real(self, entry, **kw)))
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN)
        _run(_stop(p))
        assert seen == [
            ("thinking", "internal", "plan the search"), ("text", "internal", "Starting the search."),
            ("thinking", "internal", "found it"), ("text", "internal", "Found two candidates."),
            ("text", "report", "FINAL REPORT: two files."),
            ("text", "report", "stopped (2 narration, 2 thinking, report)"),  # the AGENT-STOP bracket (unit 5)
        ]

    def test_mismatch_logs_once_and_uses_the_payload(self, isolated_home, cursors, tmp_path, monkeypatch):
        """AC-2: the file's last text differs from the payload -> everything in the
        file is internal, the payload is the report, one SIDECHAIN-MISMATCH line."""
        import cclogger.conversation as conv
        logged = []
        monkeypatch.setattr(conv, "debug_log", lambda m: logged.append(m))
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN)
        _run(_stop(p, last="PAYLOAD REPORT (trimmed)"))
        d = _sessdir(isolated_home)
        per_agent = _read(d, ".agents-explore_*")
        assert "{AGENT:explore: FINAL REPORT: two files. }" in per_agent  # kept, as internal
        assert per_agent.find("{AGENT:explore: FINAL REPORT: two files. }") < per_agent.find("{AGENT:explore: PAYLOAD REPORT (trimmed) }")
        assert per_agent.rstrip().endswith("{AGENT-STOP:explore: stopped (3 narration, 2 thinking, report) }")
        assert sum("SIDECHAIN-MISMATCH" in m for m in logged) == 1

    def test_trailing_whitespace_on_the_payload_is_not_a_mismatch(self, isolated_home, cursors, tmp_path, monkeypatch):
        """Kills N7: the payload is compared stripped, so a trailing newline
        does not demote the file's final text to an internal leg."""
        import cclogger.conversation as conv
        logged = []
        monkeypatch.setattr(conv, "debug_log", lambda m: logged.append(m))
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN)
        _run(_stop(p, last="FINAL REPORT: two files.\n  "))
        assert not any("SIDECHAIN-MISMATCH" in m for m in logged), logged
        assert _read(_sessdir(isolated_home), ".agents-explore_*").count("FINAL REPORT") == 1

    def test_payload_report_is_stamped_with_the_event_time(self, isolated_home, cursors, tmp_path):
        """Kills N8: when the payload is the report (mismatch), its stamp is the
        stop event's time, not a borrowed sidechain time."""
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN)
        _run(_stop(p, last="PAYLOAD REPORT (trimmed)"))
        per_agent = _read(_sessdir(isolated_home), ".agents-explore_*")
        assert f"[[{TS.strftime('%Y-%m-%d %H:%M:%S')}]] {{AGENT:explore: PAYLOAD REPORT (trimmed) }}" in per_agent

    def test_no_payload_message_makes_the_last_text_the_report(self, isolated_home, cursors, tmp_path, monkeypatch):
        import cclogger.conversation as conv
        seen = []
        real = conv.SessionLogger.log_entry
        monkeypatch.setattr(conv.SessionLogger, "log_entry",
                            lambda self, entry, **kw: (seen.append(entry.agent_leg), real(self, entry, **kw)))
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN)
        _run(_stop(p, last=None))
        assert seen == ["internal"] * 4 + ["report", "report"]  # the report, then the AGENT-STOP bracket

    def test_untyped_fork_without_a_sidechain_is_unchanged(self, isolated_home, cursors, tmp_path, monkeypatch):
        """AC-5: one line in the untyped feed, from the payload, and no warning."""
        import cclogger.conversation as conv
        logged = []
        monkeypatch.setattr(conv, "debug_log", lambda m: logged.append(m))
        _run(_stop(tmp_path / "never-written.jsonl", last="UNTYPED-MSG", agent_type="", agent_id="a00000000000beef"))
        d = _sessdir(isolated_home)
        feed = _read(d, ".agents-untyped_*")
        assert feed.count("[[") == 1 and "UNTYPED-MSG" in feed
        assert not any("MISMATCH" in m or "Error" in m for m in logged), logged
        assert list(d.glob(".agents-a*")) == []

    def test_main_thread_narration_is_never_labeled_agent(self, isolated_home, cursors, tmp_path):
        """AC-3, the known bug: unread main-thread text at SubagentStop time
        must not become the agent's report, and must still surface on Stop."""
        main = tmp_path / "main.jsonl"
        _write_jsonl(main, [
            {"type": "assistant", "timestamp": _utc(14, 59, 0), "message": {"content": [_text("MAIN NARRATION while the agent ran")]}},
        ])
        side = tmp_path / "agent.jsonl"
        _write_jsonl(side, SIDECHAIN)
        _run(_stop(side, transcript=str(main)))
        d = _sessdir(isolated_home)
        convo = _read(d, ".convo_*")
        assert "MAIN NARRATION" not in convo  # not consumed by the agent's stop
        assert "{AGENT:explore:\nFINAL REPORT: two files.\n}" in convo
        # the next Stop still delivers it as AI
        _run({"session_id": GUID, "transcript_path": str(main), "hook_event_name": "Stop", "stop_hook_active": False})
        convo = _read(d, ".convo_*")
        assert "{AI:\nMAIN NARRATION while the agent ran\n}" in convo
        assert "{AGENT:explore:\nMAIN NARRATION" not in convo

    def test_global_thinking_off_builds_no_thinking_entry(self, isolated_home, cursors, tmp_path, monkeypatch):
        """AC-13: with Config.thinking False no thinking LogEntry is allocated."""
        import cclogger.conversation as conv
        from cclogger.models import Config
        kinds = []
        real = conv.SessionLogger.log_entry
        monkeypatch.setattr(conv.SessionLogger, "log_entry",
                            lambda self, entry, **kw: (kinds.append(entry.kind), real(self, entry, **kw)))
        cfg = Config()
        cfg.thinking = False
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN)
        _run(_stop(p), config=cfg)
        assert kinds == ["text"] * 4  # two narration legs, the report, the AGENT-STOP bracket
        assert "AGENT-THINK" not in _read(_sessdir(isolated_home), ".sesslog_*")

    def test_resumed_agent_second_stop_emits_only_new_turns(self, isolated_home, cursors, tmp_path, monkeypatch):
        """AC-4 through the handler."""
        import cclogger.conversation as conv
        seen = []
        real = conv.SessionLogger.log_entry
        monkeypatch.setattr(conv.SessionLogger, "log_entry",
                            lambda self, entry, **kw: (seen.append(entry.raw_content), real(self, entry, **kw)))
        p = tmp_path / "agent.jsonl"
        _write_jsonl(p, SIDECHAIN[:2])
        _run(_stop(p, last="Starting the search."))
        assert seen == ["plan the search", "Starting the search.", "stopped (0 narration, 1 thinking, report)"]
        seen.clear()
        with open(p, "a", encoding="utf-8") as f:
            for e in SIDECHAIN[2:]:
                f.write(json.dumps(e) + "\n")
        _run(_stop(p))
        assert seen == ["found it", "Found two candidates.", "FINAL REPORT: two files.",
                        "stopped (1 narration, 1 thinking, report)"]


# ============================================================================
# Dispatch / internal legs on tool entries (legacy.generate_entry)
# ============================================================================

class TestToolEntryLegs:
    def _entry(self, name, agent_ctx=None):
        from cclogger.formatters.legacy import generate_entry
        from cclogger.models import CommandContent, Config, ToolInfo
        info = ToolInfo(name=name, input={}, description="", session_id=GUID, transcript_path="",
                        raw_json={}, agent_context=agent_ctx, agent_id="a1" if agent_ctx else None)
        cc = CommandContent(raw_content="x", legacy_string="x", summary_template=None)
        return generate_entry(info, Config(), cc, TS)

    def test_agent_call_on_main_thread_is_dispatch(self):
        assert self._entry("Agent").agent_leg == "dispatch"
        assert self._entry("Task").agent_leg == "dispatch"

    def test_call_inside_an_agent_is_internal(self):
        assert self._entry("Bash", agent_ctx="explore").agent_leg == "internal"
        assert self._entry("Agent", agent_ctx="explore").agent_leg == "internal"

    def test_main_thread_tool_has_no_leg(self):
        assert self._entry("Bash").agent_leg is None


# ============================================================================
# End to end through the real hook subprocess
# ============================================================================

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
    def test_agent_story_in_order_no_duplicate_tool_calls(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        main = tmp_path / "main.jsonl"
        _write_jsonl(main, [])
        side = tmp_path / "agent.jsonl"
        _write_jsonl(side, SIDECHAIN)
        base = {"session_id": GUID, "transcript_path": str(main), "cwd": "/", "permission_mode": "default"}
        events = [
            dict(base, hook_event_name="PostToolUse", tool_name="Agent",
                 tool_input={"prompt": "find the thing", "subagent_type": "Explore", "description": "search"},
                 tool_response={"result": "launched"}),
            dict(base, hook_event_name="PostToolUse", tool_name="Bash", agent_id=AGENT, agent_type="Explore",
                 tool_input={"command": "echo hi"}, tool_response={"stdout": "hi", "stderr": "", "interrupted": False}),
            _stop(side),
        ]
        _drive_hook(home, events)
        d = list((home / ".claude" / "sesslogs").glob("*"))[0]
        per_agent = _read(d, ".agents-explore_*")
        order = ["find the thing", "echo hi", "plan the search", "Starting the search.", "FINAL REPORT: two files."]
        pos = [per_agent.find(s) for s in order]
        assert all(x >= 0 for x in pos), per_agent
        assert pos == sorted(pos)
        assert per_agent.count("echo hi") == 1  # AC-6: the sidechain's tool_use block is not re-logged
        assert "AGENT-THINK" in per_agent
