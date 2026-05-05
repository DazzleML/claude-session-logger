"""Tests: tool coverage robustness + channel-aware routing for unknowns (v0.2.1).

Validates fixes from `2026-05-01__12-03-14__tool-coverage-and-channel-routing-for-unknowns.md`:
  - PowerShell handler (Bash-equivalent)
  - "other" -> "unknown" category rename
  - `unknowns` channel + `unknown` route in defaults
  - Smart fallback expanded with `command, skill, subject`
  - `?` marker prefix in entry text for unknown tools
  - Cross-process throttled warning via sentinel files

Run: python -m pytest tests/one-offs/test_unknown_tool_routing.py -v
"""

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# log-command.py has a hyphen so we need importlib
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks" / "scripts"))
_mod = importlib.import_module("log-command")

categorize_tool = _mod.categorize_tool
get_command_content = _mod.get_command_content
generate_entry = _mod.generate_entry
_default_channels = _mod._default_channels
_default_category_routes = _mod._default_category_routes
_warn_unknown_tool_once = _mod._warn_unknown_tool_once
ToolInfo = _mod.ToolInfo
Config = _mod.Config


def _make_tool_info(name: str, tool_input: dict, description: str = "") -> ToolInfo:
    """Build a ToolInfo for testing."""
    return ToolInfo(
        name=name,
        input=tool_input,
        description=description,
        session_id="test-session",
        transcript_path="",
        raw_json={"tool_name": name, "tool_input": tool_input},
        agent_context=None,
    )


class TestPowerShellHandler:
    """PowerShell tool gets Bash-equivalent handling (#PowerShell bug, v0.2.1)."""

    def test_powershell_categorized_as_bash(self):
        assert categorize_tool("PowerShell") == "bash"

    def test_powershell_extracts_command(self):
        ti = _make_tool_info("PowerShell", {"command": "Get-Process"})
        assert get_command_content(ti) == "Get-Process"

    def test_powershell_with_description_still_uses_command(self):
        ti = _make_tool_info(
            "PowerShell",
            {"command": "ls", "description": "list directory"}
        )
        assert get_command_content(ti) == "ls"


class TestUnknownCategory:
    """Renamed from 'other' to 'unknown' for clarity."""

    def test_unknown_tool_returns_unknown_category(self):
        assert categorize_tool("CompletelyMadeUpTool") == "unknown"

    def test_known_tools_still_categorized_correctly(self):
        # Spot-check a few to ensure rename didn't break categorization
        assert categorize_tool("Bash") == "bash"
        assert categorize_tool("Read") == "system"
        assert categorize_tool("Write") == "io"
        assert categorize_tool("TaskCreate") == "task"
        assert categorize_tool("Skill") == "skill"

    def test_mcp_tool_still_categorized_as_mcp(self):
        # MCP prefix check happens before TOOL_CATEGORIES lookup
        assert categorize_tool("mcp__server__some_tool") == "mcp"


class TestSmartFallback:
    """Generic fallback now checks command/skill/subject in addition to existing fields."""

    def test_fallback_picks_up_command_field(self):
        # New tool, not in any handler, but has `command` field
        ti = _make_tool_info("NewShellTool", {"command": "echo hello"})
        assert get_command_content(ti) == "echo hello"

    def test_fallback_picks_up_skill_field(self):
        ti = _make_tool_info("FutureSkillLikeTool", {"skill": "my-skill"})
        assert get_command_content(ti) == "my-skill"

    def test_fallback_picks_up_subject_field(self):
        ti = _make_tool_info("FutureTaskLike", {"subject": "Do the thing"})
        assert get_command_content(ti) == "Do the thing"

    def test_fallback_returns_empty_for_truly_novel_field(self):
        # Tool with no recognized field name returns empty (warning fires elsewhere)
        ti = _make_tool_info("ExoticTool", {"expression": "1+1", "lang": "python"})
        assert get_command_content(ti) == ""

    def test_fallback_field_priority_command_first(self):
        # When multiple fallback fields are present, `command` wins (declared first)
        ti = _make_tool_info("Ambiguous", {
            "command": "real-command",
            "pattern": "should-not-pick",
        })
        assert get_command_content(ti) == "real-command"


class TestDefaultChannels:
    """Defaults factory includes the new `unknowns` channel."""

    def test_unknowns_channel_in_defaults(self):
        channels = _default_channels()
        assert "unknowns" in channels
        assert channels["unknowns"].file_prefix == ".unknowns_"
        assert channels["unknowns"].enabled is True

    def test_existing_channels_still_present(self):
        # Updated for v0.3.0 (#28): adds `tools` channel
        channels = _default_channels()
        assert set(channels.keys()) == {"shell", "sesslog", "tasks", "unknowns", "tools"}


class TestDefaultCategoryRoutes:
    """Defaults factory includes the new `unknown` route."""

    def test_unknown_route_in_defaults(self):
        routes = _default_category_routes()
        assert "unknown" in routes
        assert routes["unknown"] == ["sesslog", "unknowns"]

    def test_unknown_route_does_not_include_shell(self):
        # Critical: keeps .shell_*.log clean of non-shell entries
        routes = _default_category_routes()
        assert "shell" not in routes["unknown"]

    def test_existing_routes_still_present(self):
        # Updated for v0.3.0 (#28): _default and task routes now include `tools`
        routes = _default_category_routes()
        assert routes["_default"] == ["shell", "sesslog", "tools"]
        assert routes["task"] == ["shell", "sesslog", "tools", "tasks"]


class TestMarkerPrefix:
    """Unknown tools get `?` prefix in log entries for grep-friendly identification."""

    def _make_config(self, verbosity=2):
        c = Config()
        c.verbosity = verbosity
        c.datetime_mode = "none"  # simpler entries for assertion
        return c

    def test_unknown_tool_gets_question_mark_prefix(self):
        ti = _make_tool_info("MysteryTool", {"command": "do something"})
        config = self._make_config()
        entry = generate_entry(ti, config, "do something", datetime(2026, 5, 1, 12, 0, 0))
        assert "{?MysteryTool:" in entry

    def test_known_tool_has_no_prefix(self):
        ti = _make_tool_info("Bash", {"command": "ls"})
        config = self._make_config()
        entry = generate_entry(ti, config, "ls", datetime(2026, 5, 1, 12, 0, 0))
        assert "{Bash:" in entry
        assert "{?Bash:" not in entry

    def test_marker_keeps_brace_anchor_intact(self):
        # Pattern `{ToolName:` (after sanitization for `?`) should still parseable
        ti = _make_tool_info("Strange", {"command": "x"})
        config = self._make_config()
        entry = generate_entry(ti, config, "x", datetime(2026, 5, 1, 12, 0, 0))
        # Marker is between `{` and tool name, NOT before `{`
        assert entry.count("{?") == 1
        assert "?{" not in entry  # Wrong placement would break opening brace anchor


class TestSentinelThrottling:
    """Cross-process throttled warning via sentinel files."""

    def test_sentinel_file_created_on_first_warn(self, tmp_path, monkeypatch):
        # Redirect sentinel dir to tmp
        monkeypatch.setattr(_mod, "UNKNOWN_TOOL_WARN_DIR", tmp_path / "warnings")
        _warn_unknown_tool_once("FirstTool", ["foo", "bar"])
        assert (tmp_path / "warnings" / "FirstTool.warned").exists()

    def test_second_call_does_not_re_log(self, tmp_path, monkeypatch):
        # Spy on debug_log to count invocations
        call_count = []
        monkeypatch.setattr(_mod, "UNKNOWN_TOOL_WARN_DIR", tmp_path / "warnings")
        monkeypatch.setattr(_mod, "debug_log", lambda msg: call_count.append(msg))

        _warn_unknown_tool_once("SameTool", ["x"])
        _warn_unknown_tool_once("SameTool", ["x"])
        _warn_unknown_tool_once("SameTool", ["x"])

        assert len(call_count) == 1, "Throttling should keep us at 1 warning per tool"

    def test_different_tools_each_get_own_warning(self, tmp_path, monkeypatch):
        call_count = []
        monkeypatch.setattr(_mod, "UNKNOWN_TOOL_WARN_DIR", tmp_path / "warnings")
        monkeypatch.setattr(_mod, "debug_log", lambda msg: call_count.append(msg))

        _warn_unknown_tool_once("ToolA", ["a"])
        _warn_unknown_tool_once("ToolB", ["b"])
        _warn_unknown_tool_once("ToolA", ["a"])  # Repeat
        _warn_unknown_tool_once("ToolC", ["c"])

        assert len(call_count) == 3, "Three distinct tools = three warnings"

    def test_sanitizes_unsafe_filename_chars(self, tmp_path, monkeypatch):
        # Tool names with slashes/colons shouldn't break sentinel creation
        monkeypatch.setattr(_mod, "UNKNOWN_TOOL_WARN_DIR", tmp_path / "warnings")
        _warn_unknown_tool_once("path/like:name", ["x"])
        # Sanitized: non-[A-Za-z0-9_\-.] becomes `_`
        sentinels = list((tmp_path / "warnings").glob("*.warned"))
        assert len(sentinels) == 1
        # Original chars stripped; only safe chars + `_` substitutes remain
        assert "/" not in sentinels[0].name
        assert ":" not in sentinels[0].name

    def test_silent_on_filesystem_error(self, tmp_path, monkeypatch):
        # Should not raise even if sentinel dir is unwritable
        monkeypatch.setattr(_mod, "UNKNOWN_TOOL_WARN_DIR", Path("/nonexistent/no-permission/dir"))
        # No assertion needed — just verify no exception
        _warn_unknown_tool_once("AnyTool", ["any"])
