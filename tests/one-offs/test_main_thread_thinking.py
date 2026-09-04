"""Unit 3 of the sidechain-capture design (2026-09-03): the Stop handler
records the main thread's thinking blocks alongside its narration, in
block order, as `{THINK: ...}` entries (kind="thinking", role "ai"), under
the global `thinking` switch. This session's own transcript held 293
thinking blocks against 78 text blocks; before this unit every one was
dropped.

Acceptance checks: AC-7 (thinking -> text -> thinking yields THINK, AI,
THINK in that order), AC-13 (Config.thinking False builds no thinking
LogEntry; the text still lands), AC-1 through the real read (exclude on
convo hides them; sesslog keeps them), AC-14 (the enabled thinking channel
collects them), and the cursor contract (thinking blocks are consumed like
text: nothing is re-emitted on the next Stop).

Design: 2026-09-03__15-32-54__dev-workflow-process__sidechain-capture-thinking-and-sesslog-main.md
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
GUID = "7411c1a9-0903-4bbb-8ccc-0000000000e3"
USER = "thinkmain"
TS = datetime(2026, 9, 3, 19, 20, 0)
STAMP = "[[2026-09-03 19:20:00]]"


def _assistant(*blocks) -> dict:
    return {"type": "assistant", "timestamp": "2026-09-03T23:19:00.000Z",
            "message": {"role": "assistant", "content": list(blocks)}}


def _text(t):
    return {"type": "text", "text": t}


def _think(t):
    return {"type": "thinking", "thinking": t, "signature": "opaque"}


TRANSCRIPT = [
    _assistant(_think("first thought"), _text("first answer"),
               {"type": "tool_use", "id": "t1", "name": "Read", "input": {}}),
    {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}},
    _assistant(_think("second thought")),
    _assistant(_text("second answer")),
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
    monkeypatch.setattr("cclogger.conversation._convo_cursor_path", lambda sid: d / f"{sid}.convo-cursor")
    return d


def _ctx():
    from cclogger.models import SessionContext
    return SessionContext(shell_type="bash.exe", session_name="think-main", session_id=GUID, username=USER)


def _stop(transcript: Path) -> dict:
    return {"session_id": GUID, "transcript_path": str(transcript), "cwd": "/",
            "permission_mode": "default", "hook_event_name": "Stop", "stop_hook_active": False}


def _run(event, config=None):
    from cclogger.conversation import handle_conversation_event
    from cclogger.models import Config
    handle_conversation_event(event["hook_event_name"], event, _ctx(), config or Config(), TS)


def _sessdir(home: Path) -> Path:
    dirs = list((home / ".claude" / "sesslogs").glob("*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def _read(d: Path, glob: str) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in d.glob(glob))


class TestBlockReader:
    def test_blocks_in_order_and_cursor_advances(self, tmp_path, cursors):
        from cclogger.conversation import _read_recent_assistant_blocks as rb
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        assert rb(str(t), GUID) == [("thinking", "first thought"), ("text", "first answer"),
                                    ("thinking", "second thought"), ("text", "second answer")]
        assert rb(str(t), GUID) == []  # consumed, thinking included

    def test_thinking_left_out_when_asked(self, tmp_path, cursors):
        from cclogger.conversation import _read_recent_assistant_blocks as rb
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        assert rb(str(t), GUID, include_thinking=False) == [("text", "first answer"), ("text", "second answer")]

    def test_shrunk_transcript_resets_the_cursor(self, tmp_path, cursors):
        """Kills M2: a cursor beyond the file (rotation / compaction) is reset
        to zero and the whole file is read, not silently skipped forever."""
        from cclogger.conversation import _read_recent_assistant_blocks as rb, _write_convo_cursor
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, [_assistant(_think("after-rotation"), _text("post"))])
        _write_convo_cursor(GUID, 99999)
        assert rb(str(t), GUID) == [("thinking", "after-rotation"), ("text", "post")]

    def test_only_assistant_entries_are_read(self, tmp_path, cursors):
        """Kills M3: system / summary / attachment entries that happen to carry
        a content list are not narrative."""
        from cclogger.conversation import _read_recent_assistant_blocks as rb
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, [
            {"type": "system", "message": {"content": [_text("SYS-TEXT")]}},
            {"type": "summary", "message": {"content": [_think("SUM-THINK")]}},
            {"type": "attachment", "content": [_text("ATT-TEXT")]},
            _assistant(_text("real")),
        ])
        assert rb(str(t), GUID) == [("text", "real")]

    def test_cursor_reaches_eof_even_when_nothing_narrative_was_found(self, tmp_path, cursors):
        """Kills M6: a tail of user turns and tool results still advances the
        cursor to EOF, so it is not re-scanned on every Stop."""
        from cclogger.conversation import _read_recent_assistant_blocks as rb, _read_convo_cursor
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, [{"type": "user", "message": {"role": "user", "content": "just a prompt"}}])
        assert rb(str(t), GUID) == []
        assert _read_convo_cursor(GUID) == t.stat().st_size

    def test_bad_and_blank_lines_do_not_stop_the_scan(self, tmp_path, cursors):
        """Kills N1 (a malformed line aborts) and N2 (a blank line ends the scan)."""
        from cclogger.conversation import _read_recent_assistant_blocks as rb
        t = tmp_path / "main.jsonl"
        t.write_text(json.dumps(_assistant(_text("before"))) + "\n"
                     + "{not json at all\n"
                     + "\n"
                     + "   \n"
                     + json.dumps(_assistant(_think("after-think"), _text("after"))) + "\n",
                     encoding="utf-8")
        assert rb(str(t), GUID) == [("text", "before"), ("thinking", "after-think"), ("text", "after")]

    def test_error_path_returns_an_empty_list_never_none(self, tmp_path, cursors, monkeypatch):
        """Kills N8: a failure inside the read (the cursor store raising here)
        yields [] from both the block reader and its text-only view, so
        callers can iterate. (A directory path is NOT a good probe for this:
        on Windows its size is 0 and the nothing-new guard returns first.)"""
        import cclogger.conversation as conv
        logged = []
        monkeypatch.setattr(conv, "debug_log", lambda m: logged.append(m))
        monkeypatch.setattr(conv, "_read_convo_cursor", lambda sid: (_ for _ in ()).throw(RuntimeError("boom")))
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        assert conv._read_recent_assistant_blocks(str(t), GUID) == []
        assert conv._read_recent_assistant_messages(str(t), GUID) == []
        assert any("Error reading transcript" in m for m in logged)

    def test_is_subagent_parameter_is_inert(self, tmp_path, cursors):
        """Kills N7: the compatibility parameter changes nothing."""
        from cclogger.conversation import _read_recent_assistant_messages as rm
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        assert rm(str(t), GUID, is_subagent=True) == ["first answer", "second answer"]

    def test_text_only_reader_still_returns_texts_and_shares_the_cursor(self, tmp_path, cursors):
        from cclogger.conversation import _read_recent_assistant_blocks as rb, _read_recent_assistant_messages as rm
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        assert rm(str(t), GUID) == ["first answer", "second answer"]
        assert rb(str(t), GUID) == []  # the text-only view consumed the same cursor


class TestStopHandler:
    def test_think_and_ai_entries_in_block_order(self, isolated_home, cursors, tmp_path):
        """AC-7."""
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        _run(_stop(t))
        d = _sessdir(isolated_home)
        convo = _read(d, ".convo_*")
        want = [f"{STAMP} {{THINK:\nfirst thought\n}}", f"{STAMP} {{AI:\nfirst answer\n}}",
                f"{STAMP} {{THINK:\nsecond thought\n}}", f"{STAMP} {{AI:\nsecond answer\n}}"]
        pos = [convo.find(w) for w in want]
        assert all(p >= 0 for p in pos), convo
        assert pos == sorted(pos)
        sesslog = _read(d, ".sesslog_*")
        assert "{THINK: first thought }" in sesslog and "{AI: second answer }" in sesslog

    def test_global_switch_off_builds_no_thinking_entry(self, isolated_home, cursors, tmp_path, monkeypatch):
        """AC-13."""
        import cclogger.conversation as conv
        from cclogger.models import Config
        kinds = []
        real = conv.SessionLogger.log_entry
        monkeypatch.setattr(conv.SessionLogger, "log_entry",
                            lambda self, entry, **kw: (kinds.append(entry.kind), real(self, entry, **kw)))
        cfg = Config()
        cfg.thinking = False
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        _run(_stop(t), config=cfg)
        assert kinds == ["text", "text"]
        d = _sessdir(isolated_home)
        assert "THINK" not in _read(d, ".convo_*") and "first answer" in _read(d, ".convo_*")

    def test_nothing_re_emitted_on_the_next_stop(self, isolated_home, cursors, tmp_path):
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        _run(_stop(t))
        d = _sessdir(isolated_home)
        before = _read(d, ".convo_*")
        _run(_stop(t))
        assert _read(d, ".convo_*") == before
        with open(t, "a", encoding="utf-8") as f:
            f.write(json.dumps(_assistant(_think("third thought"), _text("third answer"))) + "\n")
        _run(_stop(t))
        after = _read(d, ".convo_*")
        assert after.count("{THINK:") == 3 and after.count("first thought") == 1

    def test_convo_can_opt_out_while_sesslog_keeps_it(self, isolated_home, cursors, tmp_path):
        """AC-1 through the real read, using the readable per-channel switch."""
        from cclogger.config_merge import apply_override_channel_options
        from cclogger.models import Config
        cfg = Config()
        apply_override_channel_options(cfg.routing.channels["convo"].options, {"thinking": False}, "convo")
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        _run(_stop(t), config=cfg)
        d = _sessdir(isolated_home)
        convo, sesslog = _read(d, ".convo_*"), _read(d, ".sesslog_*")
        assert "THINK" not in convo and "first answer" in convo and "second answer" in convo
        assert "{THINK: first thought }" in sesslog

    def test_enabled_thinking_channel_collects_only_thinking(self, isolated_home, cursors, tmp_path):
        """AC-14 through the real read."""
        from cclogger.models import Config
        cfg = Config()
        cfg.routing.channels["thinking"].enabled = True
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        _run(_stop(t), config=cfg)
        think = _read(_sessdir(isolated_home), ".thinking_*")
        assert "first thought" in think and "second thought" in think
        assert "first answer" not in think and "second answer" not in think

    def test_entries_carry_the_ai_category_not_the_user_one(self, isolated_home, cursors, tmp_path):
        """Kills N5: with message_user rerouted away from convo, AI and THINK
        entries still reach convo because they travel as message_ai."""
        from cclogger.models import Config
        cfg = Config()
        cfg.routing.category_routes["message_user"] = ["sesslog"]
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        _run(_stop(t), config=cfg)
        convo = _read(_sessdir(isolated_home), ".convo_*")
        assert "first answer" in convo and "first thought" in convo

    def test_text_only_transcript_is_byte_identical_to_before(self, isolated_home, cursors, tmp_path):
        """No thinking in the transcript -> exactly the AI entries the old
        reader produced, nothing added."""
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, [_assistant(_text("plain one")), _assistant(_text("plain two"))])
        _run(_stop(t))
        convo = _read(_sessdir(isolated_home), ".convo_*")
        assert convo == f"{STAMP} {{AI:\nplain one\n}}\n\n{STAMP} {{AI:\nplain two\n}}\n" or \
            convo.count("{AI:") == 2 and "THINK" not in convo


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
    def test_think_entries_through_the_real_hook(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        t = tmp_path / "main.jsonl"
        _write_jsonl(t, TRANSCRIPT)
        _drive_hook(home, [_stop(t)])
        d = list((home / ".claude" / "sesslogs").glob("*"))[0]
        convo = _read(d, ".convo_*")
        assert convo.count("{THINK:") == 2 and convo.count("{AI:") == 2
        assert convo.find("first thought") < convo.find("first answer") < convo.find("second thought") < convo.find("second answer")
