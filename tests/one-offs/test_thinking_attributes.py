"""Unit 1 of the sidechain-capture design (2026-09-03): entry attributes
`kind` and `agent_leg`, the two thinking switches, the THINK / AGENT-THINK
labels, and the shipped-disabled `thinking` channel.

Maintainer decisions pinned here (Addendum 1, verbatim gist): thinking is
optional per channel; on by default in sesslog, convo and every per-agent
file; each agent tracks its own; labels `{THINK: ...}` and
`{AGENT-THINK:explore ...}`.

Acceptance checks: AC-1 (exclude on kind removes exactly the thinking
entries; second-axis rehearsal on agent_leg), AC-12 (`options.thinking:
false` is byte-equivalent to `exclude: {"kind": ["thinking"]}` and derived
files inherit it), AC-13 (global `thinking: false` parses; the extraction
side lands with units 2-3), AC-14 (the `thinking` channel collects only
kind=thinking), plus label rendering in both formatters.

Design: 2026-09-03__15-32-54__dev-workflow-process__sidechain-capture-thinking-and-sesslog-main.md
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

GUID = "e0c1ude0-0903-4bbb-8ccc-0000000000d1"
USER = "thinkuser"
TS = datetime(2026, 9, 3, 18, 0, 0)


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
    session = SessionContext(shell_type="bash.exe", session_name="think-unit",
                             session_id=GUID, username=USER)
    return SessionLogger(config or Config(), session, TS)


def _entry(kind="text", role="ai", agent_leg=None, ctx=None, text=None):
    from cclogger.models import LogEntry
    return LogEntry(raw_content=text or f"{role}-{kind}", role=role, timestamp=TS,
                    tool_name="Stop" if role == "ai" else "SubagentStop",
                    kind=kind, agent_leg=agent_leg, agent_context=ctx,
                    agent_id="a0000000000000d1" if ctx else None)


def _log(logger, entry, category="message_ai"):
    logger.log_entry(entry, tool_name=entry.tool_name, tool_category=category,
                     event_time=TS, raw_json={})


def _text(d: Path, glob: str) -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in d.glob(glob))


def _sessdir(home: Path) -> Path:
    dirs = list((home / ".claude" / "sesslogs").glob("*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


# ============================================================================
# Attributes and whitelists
# ============================================================================

class TestAttributes:
    def test_defaults(self):
        from cclogger.models import LogEntry, KIND_TEXT
        e = LogEntry(raw_content="x", role="ai")
        assert e.kind == KIND_TEXT == "text"
        assert e.agent_leg is None

    def test_whitelists_include_both_axes(self):
        from cclogger.models import COLLECT_RECOGNIZED_KEYS, EXCLUDE_RECOGNIZED_KEYS
        assert {"kind", "agent_leg"} <= COLLECT_RECOGNIZED_KEYS
        assert {"kind", "agent_leg"} <= EXCLUDE_RECOGNIZED_KEYS

    def test_constants(self):
        from cclogger.models import (AGENT_LEG_DISPATCH, AGENT_LEG_INTERNAL, AGENT_LEG_REPORT,
                                     KIND_THINKING)
        assert (AGENT_LEG_DISPATCH, AGENT_LEG_INTERNAL, AGENT_LEG_REPORT) == ("dispatch", "internal", "report")
        assert KIND_THINKING == "thinking"


# ============================================================================
# AC-1: exclude on kind, and the second axis (agent_leg)
# ============================================================================

class TestExcludeOnKind:
    def test_exclude_kind_thinking_removes_exactly_the_thinking_entries(self, isolated_home):
        from cclogger.models import Config
        cfg = Config()
        cfg.routing.channels["convo"].options.exclude = {"kind": ["thinking"]}
        logger = _logger(cfg)
        _log(logger, _entry("text", text="NARRATION-1"))
        _log(logger, _entry("thinking", text="THOUGHT-1"))
        _log(logger, _entry("text", text="NARRATION-2"))
        d = _sessdir(isolated_home)
        convo = _text(d, ".convo_*")
        sesslog = _text(d, ".sesslog_*")
        assert "NARRATION-1" in convo and "NARRATION-2" in convo and "THOUGHT-1" not in convo
        assert "THOUGHT-1" in sesslog  # untouched channel still has it

    def test_default_includes_thinking_everywhere_the_narration_goes(self, isolated_home):
        logger = _logger()
        _log(logger, _entry("thinking", text="THOUGHT-D"))
        d = _sessdir(isolated_home)
        assert "THOUGHT-D" in _text(d, ".convo_*")
        assert "THOUGHT-D" in _text(d, ".sesslog_*")

    def test_second_axis_agent_leg(self, isolated_home):
        """AC-10 rehearsal: a brand-new attribute works with no evaluator change."""
        from cclogger.models import Config
        cfg = Config()
        cfg.routing.channels["sesslog"].options.exclude = {"agent_leg": ["internal"]}
        logger = _logger(cfg)
        _log(logger, _entry("text", role="agent", agent_leg="internal", ctx="explore", text="INTERNAL-X"),
             category="message_agent")
        _log(logger, _entry("text", role="agent", agent_leg="report", ctx="explore", text="REPORT-X"),
             category="message_agent")
        d = _sessdir(isolated_home)
        sesslog = _text(d, ".sesslog_*")
        assert "REPORT-X" in sesslog and "INTERNAL-X" not in sesslog
        assert "INTERNAL-X" in _text(d, ".convo_*")

    def test_agent_thinking_reaches_the_per_agent_file(self, isolated_home):
        """Each agent tracks its own thinking: the collected .agents-<type>_* file gets it."""
        logger = _logger()
        _log(logger, _entry("thinking", role="agent", agent_leg="internal", ctx="explore", text="AGENT-THOUGHT"),
             category="message_agent")
        d = _sessdir(isolated_home)
        assert "AGENT-THOUGHT" in _text(d, ".agents-explore_*")


# ============================================================================
# AC-12: options.thinking sugar
# ============================================================================

class TestThinkingOption:
    def test_false_folds_into_exclude_at_construction(self):
        from cclogger.models import ChannelOptions
        assert ChannelOptions(thinking=False).exclude == {"kind": ["thinking"]}

    def test_false_merges_with_existing_exclude(self):
        from cclogger.models import ChannelOptions
        o = ChannelOptions(exclude={"agent_context": ["untyped"]}, thinking=False)
        assert o.exclude == {"agent_context": ["untyped"], "kind": ["thinking"]}

    def test_true_and_none_leave_exclude_alone(self):
        from cclogger.models import ChannelOptions
        assert ChannelOptions(thinking=True).exclude is None
        assert ChannelOptions().exclude is None
        assert ChannelOptions(exclude={"kind": ["thinking"]}, thinking=True).exclude == {"kind": ["thinking"]}

    def test_fold_is_idempotent_and_respects_true_spec(self):
        from cclogger.models import ChannelOptions, fold_thinking_into_exclude
        o = ChannelOptions(thinking=False)
        fold_thinking_into_exclude(o)
        assert o.exclude == {"kind": ["thinking"]}
        o2 = ChannelOptions(exclude={"kind": True}, thinking=False)
        assert o2.exclude == {"kind": True}

    @pytest.mark.parametrize("value,expected", [
        (False, False), (True, True),
        ("false", False), ("no", False), (" false ", False), ("False", False), ("0", False),
        ("true", True), ("yes", True), (" YES ", True), ("1", True),
    ])
    def test_merge_parses_bool_and_string_forms(self, value, expected):
        """Kills N3/N4/N5 (yes/no, whitespace, case) and a real bug they sat
        next to: the guard normalized the string but the parser did not, so
        ' YES ' parsed as False."""
        from cclogger.config_merge import apply_override_channel_options
        from cclogger.models import ChannelOptions
        o = ChannelOptions()
        apply_override_channel_options(o, {"thinking": value}, "convo")
        assert o.thinking is expected
        assert o.exclude == ({"kind": ["thinking"]} if expected is False else None)

    def test_merge_null_means_inherit_and_unknown_shapes_are_ignored(self):
        """Kills N6: an explicit null inherits (no fold); 7 / 'maybe' keep current."""
        from cclogger.config_merge import apply_override_channel_options
        from cclogger.models import ChannelOptions
        o = ChannelOptions()
        apply_override_channel_options(o, {"thinking": None}, "convo")
        assert o.thinking is None and o.exclude is None
        o = ChannelOptions(thinking=False)
        apply_override_channel_options(o, {"thinking": None}, "convo")
        assert o.thinking is None and o.exclude == {"kind": ["thinking"]}  # an earlier fold is not undone
        for junk in (7, "maybe", [], {}):
            o = ChannelOptions()
            apply_override_channel_options(o, {"thinking": junk}, "convo")
            assert o.thinking is None and o.exclude is None, junk

    def test_sugar_is_equivalent_to_the_exclude_form(self, isolated_home):
        """AC-12: the two spellings yield the same exclusion verdict for every
        entry kind, and the same resolved exclude on the channel."""
        from cclogger.config_merge import apply_override_channel_options
        from cclogger.models import Config
        verdicts = []
        resolved = []
        for spelling in ({"thinking": False}, {"exclude": {"kind": ["thinking"]}}):
            cfg = Config()
            apply_override_channel_options(cfg.routing.channels["convo"].options, spelling, "convo")
            resolved.append(cfg.routing.channels["convo"].options.exclude)
            logger = _logger(cfg)
            verdicts.append((
                logger._exclude_channels_for_entry(_entry("text", text="N")),
                logger._exclude_channels_for_entry(_entry("thinking", text="T")),
                logger._exclude_channels_for_entry(_entry("thinking", role="agent", ctx="explore", text="AT")),
            ))
        assert resolved[0] == resolved[1] == {"kind": ["thinking"]}
        assert verdicts[0] == verdicts[1]
        # sesslog-main (unit 6) excludes thinking by default, so it appears in
        # the verdict alongside the channel under test
        assert verdicts[0][0] == set()
        assert verdicts[0][1] == {"convo", "sesslog-main"} and verdicts[0][2] == {"convo", "sesslog-main"}

    def test_derived_per_agent_files_inherit_the_base_channel_setting(self, isolated_home):
        """agents.thinking=false must reach .agents-explore_* (declare-to-override, omit-to-inherit)."""
        from cclogger.models import Config
        cfg = Config()
        cfg.routing.channels["agents"].options.thinking = False
        from cclogger.models import fold_thinking_into_exclude
        fold_thinking_into_exclude(cfg.routing.channels["agents"].options)
        logger = _logger(cfg)
        _log(logger, _entry("thinking", role="agent", agent_leg="internal", ctx="explore", text="HIDDEN-THOUGHT"),
             category="message_agent")
        _log(logger, _entry("text", role="agent", agent_leg="report", ctx="explore", text="VISIBLE-REPORT"),
             category="message_agent")
        d = _sessdir(isolated_home)
        per_agent = _text(d, ".agents-explore_*")
        assert "VISIBLE-REPORT" in per_agent and "HIDDEN-THOUGHT" not in per_agent
        assert "HIDDEN-THOUGHT" in _text(d, ".sesslog_*")


# ============================================================================
# AC-13: the global switch (parsing; extraction lands with units 2-3)
# ============================================================================

class TestGlobalSwitch:
    def test_default_on(self):
        from cclogger.models import Config
        assert Config().thinking is True

    def test_merge_parses_top_level_key(self):
        from cclogger.config_merge import apply_override_config
        from cclogger.models import Config
        cfg = Config()
        apply_override_config(cfg, {"thinking": False})
        assert cfg.thinking is False
        apply_override_config(cfg, {"thinking": "true"})
        assert cfg.thinking is True

    def test_unrecognized_shape_leaves_capture_on(self):
        """Kills N7: the parser's default for a non-bool, non-string, non-int
        value is ON -- an odd config never silently switches thinking off."""
        from cclogger.config_merge import apply_override_config
        from cclogger.models import Config
        for junk in (None, {}, []):
            cfg = Config()
            apply_override_config(cfg, {"thinking": junk})
            assert cfg.thinking is True, junk


# ============================================================================
# AC-14: the thinking channel
# ============================================================================

class TestThinkingChannel:
    def test_shipped_disabled_with_a_kind_collector(self):
        from cclogger.models import _default_channels
        ch = _default_channels()["thinking"]
        assert ch.enabled is False and ch.file_prefix == ".thinking_"
        assert ch.options.collect == {"kind": ["thinking"]}
        assert ch.options.formatter == "chat"

    def test_disabled_channel_writes_nothing(self, isolated_home):
        logger = _logger()
        _log(logger, _entry("thinking", text="T-OFF"))
        assert list(_sessdir(isolated_home).glob(".thinking_*")) == []

    def test_enabled_channel_holds_only_thinking(self, isolated_home):
        from cclogger.models import Config
        cfg = Config()
        cfg.routing.channels["thinking"].enabled = True
        logger = _logger(cfg)
        _log(logger, _entry("text", text="MAIN-NARRATION"))
        _log(logger, _entry("thinking", text="MAIN-THOUGHT"))
        _log(logger, _entry("thinking", role="agent", agent_leg="internal", ctx="explore", text="AGENT-THOUGHT"),
             category="message_agent")
        _log(logger, _entry("text", role="agent", agent_leg="report", ctx="explore", text="AGENT-REPORT"),
             category="message_agent")
        think = _text(_sessdir(isolated_home), ".thinking_*")
        assert "MAIN-THOUGHT" in think and "AGENT-THOUGHT" in think
        assert "MAIN-NARRATION" not in think and "AGENT-REPORT" not in think


# ============================================================================
# Labels
# ============================================================================

class TestLabels:
    CONVO = None

    def _convo(self):
        from cclogger.models import ChannelOptions, NewlinePolicy
        return ChannelOptions(verbosity="full", formatter="chat", newline_policy=NewlinePolicy.RENDER)

    def test_main_thread_thinking_renders_as_THINK_in_chat(self):
        from cclogger.formatters import format_for_channel
        out = format_for_channel(_entry("thinking", text="hmm"), self._convo(), "convo")
        assert out == "[[2026-09-03 18:00:00]] {THINK:\nhmm\n}"

    def test_main_thread_text_still_renders_as_AI(self):
        from cclogger.formatters import format_for_channel
        assert format_for_channel(_entry("text", text="ok"), self._convo(), "convo") == "[[2026-09-03 18:00:00]] {AI:\nok\n}"

    def test_agent_thinking_renders_with_identity_in_chat(self):
        from cclogger.formatters import format_for_channel
        out = format_for_channel(_entry("thinking", role="agent", ctx="Explore", text="plan"), self._convo(), "convo")
        assert out == "[[2026-09-03 18:00:00]] {AGENT-THINK:explore:\nplan\n}"

    def test_agent_thinking_renders_in_default_formatter(self):
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions
        out = format_for_channel(_entry("thinking", role="agent", ctx="explore", text="plan"),
                                 ChannelOptions(verbosity="full"), "sesslog")
        assert out == "[[2026-09-03 18:00:00]] {AGENT-THINK:explore: plan }"

    def test_agent_label_never_drops_identity_but_keeps_THINK(self):
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(verbosity="full", formatter="chat", newline_policy=NewlinePolicy.RENDER,
                              agent_label="never")
        out = format_for_channel(_entry("thinking", role="agent", ctx="explore", text="plan"), opts, "convo")
        assert out.startswith("[[2026-09-03 18:00:00]] {AGENT-THINK:\n")

    def test_per_channel_role_labels_can_rename_both(self):
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(verbosity="full", formatter="chat", newline_policy=NewlinePolicy.RENDER,
                              role_labels={"think": "THOUGHT", "agent-think": "AGENT-THOUGHT"})
        assert format_for_channel(_entry("thinking", text="a"), opts, "convo").startswith("[[2026-09-03 18:00:00]] {THOUGHT:")
        assert format_for_channel(_entry("thinking", role="agent", ctx="oracle", text="b"), opts, "convo").startswith(
            "[[2026-09-03 18:00:00]] {AGENT-THOUGHT:oracle:")

    def test_thinking_on_a_non_conversation_role_keeps_its_own_label(self):
        """Kills N2: only ai and agent thinking get the THINK labels; any
        other role carrying kind=thinking displays under its own role."""
        from cclogger.formatters import format_for_channel
        out = format_for_channel(_entry("thinking", role="user", text="hm"), self._convo(), "convo")
        assert out.startswith("[[2026-09-03 18:00:00]] {USER:\n")

    def test_missing_role_displays_as_unknown_not_ai(self, tmp_path, monkeypatch):
        """Kills N1: an entry with no role is `??:unknown`, never silently AI."""
        import cclogger.debug as dbg
        monkeypatch.setattr(dbg, "UNKNOWN_ROLE_WARN_DIR", tmp_path / "role-warn")
        from cclogger.formatters import format_for_channel
        from cclogger.models import LogEntry
        e = LogEntry(raw_content="x", role="", timestamp=TS, kind="thinking")
        out = format_for_channel(e, self._convo(), "convo")
        assert out.startswith("[[2026-09-03 18:00:00]] {??:unknown:\n")

    def test_verbosity_still_resolves_on_the_entry_role(self):
        """A per-role verbosity for `ai` applies to THINK entries too (role unchanged)."""
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"ai": {"max_chars": 3}})
        out = format_for_channel(_entry("thinking", text="abcdef"), opts, "sesslog")
        assert out == "[[2026-09-03 18:00:00]] {THINK: abc... }"
