"""Unit 6 of the sidechain-capture design (2026-09-03): `sesslog-main`, the
session as the main thread saw it. A shipped default channel defined
entirely in config on the entry attributes: sesslog's routes and
verbosity, minus every agent's internal legs (its own tool calls,
narration and thinking) and minus all thinking. Dispatch, the START/STOP
brackets, the report, main-thread tool calls, user prompts and AI
narration stay. Enabled by default (maintainer, Addendum 5: "enabled by
default but we want to make it easy to turn off"), so the off switch is
the first thing tested here.

Acceptance check AC-11: for the mixed fixture below, sesslog-main
contains the user line, the AI narration, the dispatch, the report and
every main-thread tool call, and zero agent-internal or thinking lines.

Design: 2026-09-03__15-32-54__dev-workflow-process__sidechain-capture-thinking-and-sesslog-main.md
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

GUID = "5e55109a-0903-4bbb-8ccc-0000000000e6"
USER = "mainuser"
TS = datetime(2026, 9, 3, 21, 40, 0)


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _logger(config=None):
    from cclogger.logger import SessionLogger
    from cclogger.models import Config, SessionContext
    return SessionLogger(config or Config(),
                         SessionContext(shell_type="bash.exe", session_name="main-unit", session_id=GUID, username=USER),
                         TS)


def _sessdir(home: Path) -> Path:
    dirs = list((home / ".claude" / "sesslogs").glob("*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def _read(d: Path, glob: str) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in d.glob(glob))


def _prose(text, role="ai", kind="text", leg=None, ctx=None, tool="Stop"):
    from cclogger.models import LogEntry
    return LogEntry(raw_content=text, role=role, timestamp=TS, tool_name=tool, kind=kind,
                    agent_leg=leg, agent_context=ctx, agent_id="a0000000000000e6" if ctx else None)


def _tool(payload: dict):
    from cclogger.formatters import get_command_content_structured
    from cclogger.formatters.legacy import generate_entry
    from cclogger.models import Config, ToolInfo
    info = ToolInfo.from_json(payload)
    return generate_entry(info, Config(), get_command_content_structured(info, Config()), TS), info


def _fixture(logger):
    """The mixed session: main thread + one Explore agent + one failure."""
    from cclogger.categorize import categorize_tool
    logger.log_entry(_prose("USER PROMPT", role="user", tool="UserPromptSubmit"), tool_name="UserPromptSubmit",
                     tool_category="message_user", event_time=TS, raw_json={})
    logger.log_entry(_prose("MAIN THOUGHT", kind="thinking"), tool_name="Stop", tool_category="message_ai",
                     event_time=TS, raw_json={})
    logger.log_entry(_prose("MAIN NARRATION"), tool_name="Stop", tool_category="message_ai", event_time=TS, raw_json={})
    base = {"session_id": GUID, "transcript_path": "", "cwd": "/", "permission_mode": "default"}
    for payload in (
        dict(base, hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "echo MAIN-TOOL"},
             tool_response={"stdout": "", "stderr": "", "interrupted": False}),
        dict(base, hook_event_name="PostToolUse", tool_name="Agent",
             tool_input={"prompt": "DISPATCH PROMPT", "subagent_type": "Explore", "description": "find things"},
             tool_response={"result": "launched"}),
        dict(base, hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "echo AGENT-INTERNAL-TOOL"},
             tool_response={"stdout": "", "stderr": "", "interrupted": False}, agent_id="a0000000000000e6", agent_type="Explore"),
        dict(base, hook_event_name="PostToolUseFailure", tool_name="Read", tool_input={"file_path": "C:/MAIN-FAILED.md"},
             tool_error="File does not exist."),
    ):
        entry, info = _tool(payload)
        logger.log_entry(entry, info.name, categorize_tool(info.name), event_time=TS, raw_json=info.raw_json)
    for text, role, kind, leg in (
        ("started", "agent-start", "text", "dispatch"),
        ("AGENT THOUGHT", "agent", "thinking", "internal"),
        ("AGENT NARRATION", "agent", "text", "internal"),
        ("AGENT REPORT", "agent", "text", "report"),
        ("stopped (1 narration, 1 thinking, report)", "agent-stop", "text", "report"),
    ):
        logger.log_entry(_prose(text, role=role, kind=kind, leg=leg, ctx="explore", tool="SubagentStop"),
                         tool_name="SubagentStop", tool_category="message_agent", event_time=TS, raw_json={})


class TestShippedDefinition:
    def test_enabled_by_default_with_its_prefix(self):
        from cclogger.models import _default_channels
        ch = _default_channels()["sesslog-main"]
        assert ch.enabled is True and ch.file_prefix == ".sesslog-main_"

    def test_off_switch_is_one_line_of_config(self):
        """The maintainer's condition: enabled, but easy to turn off."""
        from cclogger.config_merge import apply_override_config
        from cclogger.models import Config
        cfg = Config()
        apply_override_config(cfg, {"routing": {"channels": {"sesslog-main": {"enabled": False}}}})
        assert cfg.routing.channels["sesslog-main"].enabled is False
        assert cfg.routing.channels["sesslog"].enabled is True  # the complete record is untouched

    def test_mirrors_sesslog_verbosity_and_excludes_internals_and_thinking(self):
        from cclogger.models import _default_channels
        ch = _default_channels()
        assert ch["sesslog-main"].options.verbosity == ch["sesslog"].options.verbosity
        assert ch["sesslog-main"].options.exclude == {"agent_leg": ["internal"], "kind": ["thinking"]}
        assert ch["sesslog-main"].options.thinking is False

    def test_every_sesslog_route_and_override_names_sesslog_main(self):
        from cclogger.models import _default_category_routes, _default_tool_overrides
        for name, route in {**_default_category_routes(), **_default_tool_overrides()}.items():
            if "sesslog" in route:
                assert "sesslog-main" in route, name
                assert route.index("sesslog-main") == route.index("sesslog") + 1, name
            else:
                assert "sesslog-main" not in route, name


class TestContents:
    def test_ac11_the_main_thread_view(self, isolated_home):
        logger = _logger()
        _fixture(logger)
        d = _sessdir(isolated_home)
        main = _read(d, ".sesslog-main_*")
        full = _read(d, ".sesslog_*")
        for keep in ("USER PROMPT", "MAIN NARRATION", "echo MAIN-TOOL", "DISPATCH PROMPT",
                     "AGENT-START:explore", "AGENT REPORT", "AGENT-STOP:explore", "MAIN-FAILED.md", "[FAILED: File does not exist.]"):
            assert keep in main, keep
        for drop in ("MAIN THOUGHT", "AGENT THOUGHT", "AGENT NARRATION", "AGENT-INTERNAL-TOOL", "THINK"):
            assert drop not in main, drop
        # sesslog is still the complete record
        for present in ("MAIN THOUGHT", "AGENT THOUGHT", "AGENT NARRATION", "AGENT-INTERNAL-TOOL"):
            assert present in full, present

    def test_disabled_writes_nothing(self, isolated_home):
        from cclogger.config_merge import apply_override_config
        from cclogger.models import Config
        cfg = Config()
        apply_override_config(cfg, {"routing": {"channels": {"sesslog-main": {"enabled": False}}}})
        logger = _logger(cfg)
        _fixture(logger)
        d = _sessdir(isolated_home)
        assert list(d.glob(".sesslog-main_*")) == []
        assert "USER PROMPT" in _read(d, ".sesslog_*")

    def test_user_can_turn_thinking_back_on_for_it(self, isolated_home):
        """One config line reverses the quiet default without touching the internals rule."""
        from cclogger.models import Config
        cfg = Config()
        cfg.routing.channels["sesslog-main"].options.thinking = None
        cfg.routing.channels["sesslog-main"].options.exclude = {"agent_leg": ["internal"]}
        logger = _logger(cfg)
        _fixture(logger)
        main = _read(_sessdir(isolated_home), ".sesslog-main_*")
        assert "MAIN THOUGHT" in main and "AGENT THOUGHT" not in main and "AGENT NARRATION" not in main
