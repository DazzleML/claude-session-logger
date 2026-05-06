"""Tests: conversation channels (sub-issues #33-#35).

Validates the convo channel + message_user / message_ai / message_agent
categories + UserPromptSubmit / Stop / SubagentStop event handlers.

Note: live event handler integration with real Claude Code requires
manual checklist verification. These tests cover the unit logic with
mocked payloads.

Run: python -m pytest tests/one-offs/test_conversation_channels.py -v
"""

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks" / "scripts"))
_mod = importlib.import_module("log-command")

_default_channels = _mod._default_channels
_default_category_routes = _mod._default_category_routes
_extract_text_from_assistant_entry = _mod._extract_text_from_assistant_entry
_read_recent_assistant_messages = _mod._read_recent_assistant_messages
_read_convo_cursor = _mod._read_convo_cursor
_write_convo_cursor = _mod._write_convo_cursor


class TestConvoChannelDefaults:
    """The convo channel exists in defaults, enabled."""

    def test_convo_channel_in_defaults(self):
        channels = _default_channels()
        assert "convo" in channels
        assert channels["convo"].file_prefix == ".convo_"
        assert channels["convo"].enabled is True


class TestMessageCategoryRoutes:
    """message_user, message_ai, message_agent route to convo + sesslog only."""

    def test_message_user_route(self):
        routes = _default_category_routes()
        assert routes["message_user"] == ["sesslog", "convo"]

    def test_message_ai_route(self):
        routes = _default_category_routes()
        assert routes["message_ai"] == ["sesslog", "convo"]

    def test_message_agent_route(self):
        routes = _default_category_routes()
        assert routes["message_agent"] == ["sesslog", "convo"]

    def test_message_routes_NOT_in_shell(self):
        # Critical: prose belongs in convo, not shell history
        routes = _default_category_routes()
        for cat in ("message_user", "message_ai", "message_agent"):
            assert "shell" not in routes[cat], f"{cat} must not route to shell"

    def test_message_routes_NOT_in_tools(self):
        # Tools channel is for AI activity, not prose
        routes = _default_category_routes()
        for cat in ("message_user", "message_ai", "message_agent"):
            assert "tools" not in routes[cat], f"{cat} must not route to tools"


class TestExtractTextFromAssistantEntry:
    """Schema-flexible text extraction from transcript assistant entries."""

    def test_message_content_shape(self):
        # {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello"}]},
        }
        assert _extract_text_from_assistant_entry(entry) == ["Hello"]

    def test_role_content_shape(self):
        # {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}
        entry = {
            "role": "assistant",
            "content": [{"type": "text", "text": "World"}],
        }
        assert _extract_text_from_assistant_entry(entry) == ["World"]

    def test_multiple_text_blocks(self):
        entry = {
            "message": {
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "tool_use", "name": "Bash"},  # ignored
                    {"type": "text", "text": "second"},
                ]
            },
        }
        assert _extract_text_from_assistant_entry(entry) == ["first", "second"]

    def test_no_text_blocks_returns_empty(self):
        entry = {
            "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
        }
        assert _extract_text_from_assistant_entry(entry) == []

    def test_empty_text_blocks_filtered(self):
        entry = {
            "message": {
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "text", "text": "   "},
                    {"type": "text", "text": "real content"},
                ]
            },
        }
        assert _extract_text_from_assistant_entry(entry) == ["real content"]

    def test_malformed_entry_returns_empty(self):
        # Various malformed shapes should not crash
        assert _extract_text_from_assistant_entry({}) == []
        assert _extract_text_from_assistant_entry({"role": "user"}) == []
        assert _extract_text_from_assistant_entry({"content": "not a list"}) == []


class TestReadRecentAssistantMessages:
    """Cursor-based incremental transcript reading."""

    def _write_transcript(self, path: Path, entries: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8"
        )

    def _isolate_cursor_state(self, tmp_path, monkeypatch):
        """Redirect cursor file location to tmp so test runs don't leak state."""
        cursor_dir = tmp_path / "session-states"
        cursor_dir.mkdir()
        monkeypatch.setattr(
            _mod, "_convo_cursor_path",
            lambda sid: cursor_dir / f"{sid}.convo-cursor"
        )

    def test_reads_all_when_cursor_at_zero(self, tmp_path, monkeypatch):
        self._isolate_cursor_state(tmp_path, monkeypatch)
        transcript = tmp_path / "test.jsonl"
        self._write_transcript(transcript, [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "msg1"}]}},
            {"type": "user", "content": "user msg"},  # ignored
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "msg2"}]}},
        ])
        # No prior cursor for this session
        texts = _read_recent_assistant_messages(str(transcript), "fresh-session-1")
        assert texts == ["msg1", "msg2"]

    def test_returns_empty_when_no_new_content(self, tmp_path, monkeypatch):
        self._isolate_cursor_state(tmp_path, monkeypatch)
        transcript = tmp_path / "test.jsonl"
        self._write_transcript(transcript, [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
        ])
        # First read consumes content
        sess_id = "no-new-content-session"
        first = _read_recent_assistant_messages(str(transcript), sess_id)
        assert first == ["first"]
        # Second read with no new content returns empty
        second = _read_recent_assistant_messages(str(transcript), sess_id)
        assert second == []

    def test_picks_up_new_content_after_cursor(self, tmp_path, monkeypatch):
        self._isolate_cursor_state(tmp_path, monkeypatch)
        transcript = tmp_path / "test.jsonl"
        sess_id = "incremental-session"
        # Initial content
        self._write_transcript(transcript, [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
        ])
        first = _read_recent_assistant_messages(str(transcript), sess_id)
        assert first == ["first"]
        # Append more content (preserving newline-separated JSONL)
        with open(transcript, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "second"}]},
            }) + "\n")
        second = _read_recent_assistant_messages(str(transcript), sess_id)
        assert second == ["second"]

    def test_handles_missing_transcript_gracefully(self, tmp_path):
        nonexistent = tmp_path / "does-not-exist.jsonl"
        texts = _read_recent_assistant_messages(str(nonexistent), "any-session")
        assert texts == []

    def test_handles_empty_transcript_path(self):
        texts = _read_recent_assistant_messages("", "any-session")
        assert texts == []

    def test_resets_cursor_when_transcript_shrinks(self, tmp_path, monkeypatch):
        self._isolate_cursor_state(tmp_path, monkeypatch)
        # Simulate transcript rotation -- file is smaller than recorded cursor
        transcript = tmp_path / "rotated.jsonl"
        self._write_transcript(transcript, [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "after-rotation"}]}},
        ])
        # Manually set a cursor BEYOND current file size
        sess_id = "rotated-session"
        _write_convo_cursor(sess_id, 9999)
        # Read should detect shrink and reset to 0
        texts = _read_recent_assistant_messages(str(transcript), sess_id)
        assert texts == ["after-rotation"]


class TestCursorPersistence:
    """Cursor read/write helpers."""

    def test_missing_cursor_returns_zero(self, tmp_path, monkeypatch):
        cursor_dir = tmp_path / "states"
        cursor_dir.mkdir()
        monkeypatch.setattr(
            _mod, "_convo_cursor_path",
            lambda sid: cursor_dir / f"{sid}.convo-cursor"
        )
        offset = _read_convo_cursor("any-id")
        assert offset == 0

    def test_write_then_read_round_trip(self, tmp_path, monkeypatch):
        cursor_dir = tmp_path / "states"
        cursor_dir.mkdir()
        monkeypatch.setattr(
            _mod, "_convo_cursor_path",
            lambda sid: cursor_dir / f"{sid}.convo-cursor"
        )
        _write_convo_cursor("roundtrip", 12345)
        assert _read_convo_cursor("roundtrip") == 12345
