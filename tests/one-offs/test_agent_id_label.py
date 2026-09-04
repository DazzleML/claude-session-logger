"""Unit 7 of the sidechain-capture design (2026-09-03): the agent-id label
mode. On request (`agent_label: "id"` / `"auto-id"`) every label that shows
an agent's identity carries the first AGENT_ID_LABEL_CHARS (8) characters of
its id -- `{Bash|explore/a7c41e0b: ...}`, `{AGENT:explore/a7c41e0b ...}`,
`{AGENT-THINK:explore/a7c41e0b ...}`, the START/STOP brackets -- so
concurrent runs of one type read apart; the bracket lines then carry the
full id once (`[id a7c41e0b9d2f53e18]`). Under `auto-id` inside the agent's
own file the type is dropped and the id kept. The untyped bucket, which
carried its full id on every line since 2026-09-02, moves to the same
8-character rule. `always` / `auto` / `never` are byte-identical to before
for typed agents.

Measured before the width was chosen: 712 agent ids on the maintainer's box,
all 17 hex characters, all beginning with a constant `a`; 712 distinct
8-character prefixes.

Design: 2026-09-03__15-32-54__dev-workflow-process__sidechain-capture-thinking-and-sesslog-main.md (Addendum 7)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TS = datetime(2026, 9, 3, 22, 40, 0)
STAMP = "[[2026-09-03 22:40:00]]"
GUID = "7e0d4c2a-0903-4bbb-8ccc-0000000000e7"
FULL = "a7c41e0b9d2f53e18"
SHORT = "a7c41e0b"
MODES = ("always", "auto", "never", "id", "auto-id")


def _fmt(entry, opts, channel="sesslog"):
    from cclogger.formatters import format_for_channel
    from cclogger.models import Config
    return format_for_channel(entry, opts, channel, Config())


def _opts(mode="always", **kw):
    """Channel options for one mode. Full verbosity so bodies are not cut
    at the 20-character global preview; the chat shape asks for the convo
    channel's RENDER newlines explicitly (formatter alone does not)."""
    from cclogger.models import ChannelOptions, NewlinePolicy
    if kw.get("formatter") == "chat":
        kw.setdefault("newline_policy", NewlinePolicy.RENDER)
    return ChannelOptions(agent_label=mode, verbosity="full", **kw)


def _prose(role="agent", ctx="Explore", agent_id=FULL, text="report text", kind="text"):
    from cclogger.models import LogEntry
    return LogEntry(raw_content=text, role=role, timestamp=TS, tool_name="SubagentStop",
                    agent_context=ctx, agent_id=agent_id, kind=kind)


def _tool(name="Bash", ctx="Explore", agent_id=FULL, tool_input=None, event="PostToolUse", **extra):
    """A tool entry through the real generator. ctx None = main thread;
    ctx "" = one of Claude Code's untyped side-queries."""
    from cclogger.formatters import get_command_content_structured
    from cclogger.formatters.legacy import generate_entry
    from cclogger.models import Config, ToolInfo
    payload = {"hook_event_name": event, "tool_name": name,
               "tool_input": tool_input if tool_input is not None else {"command": "echo hi"},
               "session_id": GUID, "transcript_path": "", "cwd": "/", **extra}
    if event == "PostToolUse" and "tool_response" not in payload and "tool_error" not in payload:
        payload["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False}
    if ctx is not None:
        payload["agent_id"] = agent_id
        payload["agent_type"] = ctx
    info = ToolInfo.from_json(payload)
    cfg = Config()
    return generate_entry(info, cfg, get_command_content_structured(info, cfg), TS)


# ============================================================================
# The label form of an id
# ============================================================================

class TestShortAgentId:
    def test_first_eight_characters(self):
        from cclogger.models import AGENT_ID_LABEL_CHARS, short_agent_id
        assert AGENT_ID_LABEL_CHARS == 8
        assert short_agent_id(FULL) == SHORT and len(SHORT) == 8

    def test_short_ids_pass_through_whole(self):
        from cclogger.models import short_agent_id
        assert short_agent_id("a1") == "a1"
        assert short_agent_id("a7c41e0b") == "a7c41e0b"

    def test_none_and_empty(self):
        from cclogger.models import short_agent_id
        assert short_agent_id(None) is None
        assert short_agent_id("") is None

    def test_non_string_is_stringified(self):
        from cclogger.models import short_agent_id
        assert short_agent_id(12345678901) == "12345678"


# ============================================================================
# One decision, every mode: what identity does this channel show?
# ============================================================================

class TestIdentityTable:
    @pytest.mark.parametrize("mode,channel,ctx,agent_id,expected", [
        ("always", "sesslog", "Explore", FULL, "explore"),
        ("auto", "sesslog", "Explore", FULL, "explore"),
        ("auto", "agents-explore", "Explore", FULL, None),
        ("never", "sesslog", "Explore", FULL, None),
        ("id", "sesslog", "Explore", FULL, f"explore/{SHORT}"),
        ("id", "agents-explore", "Explore", FULL, f"explore/{SHORT}"),   # id never drops the type
        ("auto-id", "sesslog", "Explore", FULL, f"explore/{SHORT}"),
        ("auto-id", "agents-explore", "Explore", FULL, SHORT),
        ("id", "sesslog", "Explore", None, "explore"),                   # nothing to shorten
        ("never", "agents-explore", "Explore", FULL, None),
        # the untyped bucket: the id in every mode that shows identity
        ("always", "sesslog", "untyped", FULL, f"untyped/{SHORT}"),
        ("auto", "agents-untyped", "untyped", FULL, SHORT),
        ("id", "sesslog", "untyped", FULL, f"untyped/{SHORT}"),
        ("auto-id", "agents-untyped", "untyped", FULL, SHORT),
        ("never", "sesslog", "untyped", FULL, None),
        # the main thread has no identity to show
        ("id", "sesslog", None, FULL, None),
    ])
    def test_identity(self, mode, channel, ctx, agent_id, expected):
        from cclogger.formatters.default import DefaultFormatter
        from cclogger.models import Config
        f = DefaultFormatter(_opts(mode), channel, Config())
        assert f._agent_identity_for_display(_prose(ctx=ctx, agent_id=agent_id)) == expected

    def test_an_unnormalizable_context_shows_nothing_even_with_an_id(self):
        """Kills N4 (u7 sweep round 2): a context the subtype normalizer
        reduces to nothing (`!!!`) has no identity to show, so the id modes
        must not render `None/a7c41e0b`."""
        from cclogger.formatters.default import DefaultFormatter
        from cclogger.models import Config
        f = DefaultFormatter(_opts("id"), "sesslog", Config())
        assert f._agent_identity_for_display(_prose(ctx="!!!")) is None
        out = _fmt(_prose(ctx="!!!"), _opts("id"))
        assert "None" not in out and SHORT not in out and "{AGENT: report text }" in out

    def test_a_channel_without_options_is_always(self):
        """Kills N2 (u7 sweep round 2): no ChannelOptions at all means the
        shipped default, never an id mode."""
        from cclogger.formatters.default import DefaultFormatter
        from cclogger.models import Config
        f = DefaultFormatter(None, "sesslog", Config())
        assert f._agent_label_mode() == "always"
        assert f._agent_identity_for_display(_prose()) == "explore"
        assert f._agent_id_suffix(_prose(role="agent-stop")) == ""

    def test_the_full_id_is_never_an_identity(self):
        from cclogger.formatters.default import DefaultFormatter
        from cclogger.models import Config
        for mode in MODES:
            for ctx in ("Explore", "untyped"):
                got = DefaultFormatter(_opts(mode), "sesslog", Config())._agent_identity_for_display(_prose(ctx=ctx))
                assert not got or FULL not in got, (mode, ctx, got)


# ============================================================================
# Tool labels (the strings baked at generation + the template the formatter fills)
# ============================================================================

class TestToolLabels:
    def test_id_mode_in_sesslog(self):
        out = _fmt(_tool(), _opts("id"))
        assert f"{{Bash|explore/{SHORT}: echo hi" in out
        assert FULL not in out

    def test_always_is_the_baked_legacy_string(self):
        e = _tool()
        out = _fmt(e, _opts("always"))
        assert out == e.metadata["_legacy_complete"]
        assert "{Bash|Explore: echo hi" in out  # the v0.3.6 case, byte for byte

    def test_never_and_auto_in_own_file_are_plain(self):
        assert "{Bash: echo hi" in _fmt(_tool(), _opts("never"))
        assert "{Bash: echo hi" in _fmt(_tool(), _opts("auto"), "agents-explore")
        assert "{Bash|Explore: echo hi" in _fmt(_tool(), _opts("auto"), "sesslog")

    def test_auto_id_forms(self):
        assert f"{{Bash|{SHORT}: echo hi" in _fmt(_tool(), _opts("auto-id"), "agents-explore")
        assert f"{{Bash|explore/{SHORT}: echo hi" in _fmt(_tool(), _opts("auto-id"), "sesslog")

    def test_template_path_gets_the_id(self):
        e = _tool("Edit", tool_input={"file_path": "C:/x.py", "old_string": "aaa", "new_string": "bbb"})
        assert e.summary and "{snippet}" in e.summary  # fixture fact: Edit renders through the template path
        out = _fmt(e, _opts("id"))
        assert f"{{Edit|explore/{SHORT}:" in out and "x.py" in out
        assert "{Edit|Explore:" in _fmt(e, _opts("always"))
        assert "{Edit:" in _fmt(e, _opts("never"))

    def test_unknown_tool_keeps_its_question_mark(self):
        out = _fmt(_tool("MysteryTool", tool_input={"command": "x"}), _opts("id"))
        assert f"{{?MysteryTool|explore/{SHORT}:" in out

    def test_failure_marker_survives_the_id_form(self):
        e = _tool("Read", tool_input={"file_path": "C:/gone.md"}, event="PostToolUseFailure",
                  tool_error="File does not exist.")
        for mode in MODES:
            out = _fmt(e, _opts(mode))
            assert "[FAILED: File does not exist.]" in out, mode
        assert f"{{Read|explore/{SHORT}:" in _fmt(e, _opts("id"))

    def test_failure_marker_survives_on_the_template_path_too(self):
        """Kills M11 (u7 sweep): a failed Edit renders through the `{snippet}`
        template, whose labelled copy must carry the marker like the
        `always` one does -- in the id modes, under never, and in the
        agent's own file under auto."""
        e = _tool("Edit", tool_input={"file_path": "C:/x.py", "old_string": "aaa", "new_string": "bbb"},
                  event="PostToolUseFailure", tool_error="String to replace not found in file.")
        assert e.summary and "{snippet}" in e.summary  # fixture fact: the template path
        for mode, channel in (("id", "sesslog"), ("auto-id", "agents-explore"), ("never", "sesslog"),
                              ("auto", "agents-explore"), ("always", "sesslog")):
            out = _fmt(e, _opts(mode), channel)
            assert "[FAILED: String to replace not found in file.]" in out, (mode, channel)
        assert f"{{Edit|explore/{SHORT}:" in _fmt(e, _opts("id"))

    def test_main_thread_entry_untouched_by_the_id_modes(self):
        e = _tool(ctx=None)
        for mode in MODES:
            out = _fmt(e, _opts(mode))
            assert "{Bash: echo hi" in out and "|" not in out, mode

    def test_sentinel_never_leaks(self):
        from cclogger.formatters.legacy import LABEL_SENTINEL
        for e in (_tool(), _tool(ctx=""), _tool(ctx=None),
                  _tool("Edit", tool_input={"file_path": "C:/x.py", "old_string": "a", "new_string": "b"})):
            for mode in MODES:
                for channel in ("sesslog", "agents-explore", "agents-untyped", "tools"):
                    out = _fmt(e, _opts(mode), channel)
                    assert LABEL_SENTINEL not in out and "\x00" not in out, (mode, channel)


# ============================================================================
# Prose labels: AGENT, AGENT-THINK, the brackets
# ============================================================================

class TestProseLabels:
    def test_report_in_a_default_channel(self):
        assert _fmt(_prose(), _opts("id")) == f"{STAMP} {{AGENT:explore/{SHORT}: report text }}"

    def test_report_in_the_chat_formatter(self):
        out = _fmt(_prose(), _opts("id", formatter="chat"), "convo")
        assert f"{{AGENT:explore/{SHORT}:\nreport text\n}}" in out

    def test_thinking_label(self):
        assert f"{{AGENT-THINK:explore/{SHORT}:" in _fmt(_prose(kind="thinking"), _opts("id"))

    def test_bracket_labels(self):
        assert f"{{AGENT-START:explore/{SHORT}:" in _fmt(_prose(role="agent-start", text="started"), _opts("id"))
        assert f"{{AGENT-STOP:explore/{SHORT}:" in _fmt(_prose(role="agent-stop", text="stopped"), _opts("id"))

    def test_auto_id_in_the_agents_own_file(self):
        assert _fmt(_prose(), _opts("auto-id"), "agents-explore") == f"{STAMP} {{AGENT:{SHORT}: report text }}"

    def test_the_other_modes_are_unchanged(self):
        assert _fmt(_prose(), _opts("always")) == f"{STAMP} {{AGENT:explore: report text }}"
        assert _fmt(_prose(), _opts("auto"), "agents-explore") == f"{STAMP} {{AGENT: report text }}"
        assert _fmt(_prose(), _opts("never")) == f"{STAMP} {{AGENT: report text }}"


# ============================================================================
# The mapping lives in the log: the full id once, on the bracket lines
# ============================================================================

class TestBracketFullId:
    STOP = "stopped (1 narration, 0 thinking, report)"

    def test_stop_carries_the_full_id_under_id(self):
        out = _fmt(_prose(role="agent-stop", text=self.STOP), _opts("id"))
        assert out == f"{STAMP} {{AGENT-STOP:explore/{SHORT}: {self.STOP} [id {FULL}] }}"

    def test_start_too_in_the_chat_shape(self):
        out = _fmt(_prose(role="agent-start", text="started"), _opts("id", formatter="chat"), "convo")
        assert out.endswith(f"{{AGENT-START:explore/{SHORT}:\nstarted [id {FULL}]\n}}")

    def test_auto_id_in_the_agents_own_file(self):
        out = _fmt(_prose(role="agent-stop", text=self.STOP), _opts("auto-id"), "agents-explore")
        assert out == f"{STAMP} {{AGENT-STOP:{SHORT}: {self.STOP} [id {FULL}] }}"

    def test_not_under_the_other_modes(self):
        for mode in ("always", "auto", "never"):
            out = _fmt(_prose(role="agent-stop", text=self.STOP), _opts(mode))
            assert "[id " not in out and FULL not in out, mode

    def test_only_the_bracket_lines(self):
        for role, kind in (("agent", "text"), ("agent", "thinking")):
            out = _fmt(_prose(role=role, kind=kind), _opts("id"))
            assert "[id " not in out and FULL not in out, (role, kind)

    def test_no_id_means_no_suffix(self):
        out = _fmt(_prose(role="agent-stop", text=self.STOP, agent_id=None), _opts("id"))
        assert out == f"{STAMP} {{AGENT-STOP:explore: {self.STOP} }}"

    def test_frame_stays_matched(self):
        out = _fmt(_prose(role="agent-stop", text=self.STOP), _opts("id"))
        assert out.count("{") == out.count("}") == 1

    def test_the_full_id_survives_a_truncating_channel(self):
        """Kills N11 (u7 sweep round 2): the suffix goes on AFTER the body is
        cut to the channel's max_chars, in both formatters, so a channel that
        previews bodies still records the one full id."""
        from cclogger.models import ChannelOptions, NewlinePolicy
        e = _prose(role="agent-stop", text=self.STOP)
        default_out = _fmt(e, ChannelOptions(agent_label="id", verbosity={"max_chars": 12}))
        chat_out = _fmt(e, ChannelOptions(agent_label="id", formatter="chat", verbosity={"max_chars": 12},
                                          newline_policy=NewlinePolicy.RENDER), "convo")
        for out in (default_out, chat_out):
            assert f"[id {FULL}]" in out, out
            assert "report)" not in out, out  # the body itself was cut


# ============================================================================
# The untyped bucket on the same rule
# ============================================================================

class TestUntypedShortRule:
    def test_tool_label_from_real_generation(self):
        e = _tool(ctx="")
        out = _fmt(e, _opts("always"))
        assert f"{{Bash|untyped/{SHORT}: echo hi" in out and FULL not in out
        assert out == e.metadata["_legacy_complete"]

    def test_prose_in_every_mode(self):
        assert f"{{AGENT:untyped/{SHORT}:" in _fmt(_prose(ctx="untyped"), _opts("always"))
        assert f"{{AGENT:untyped/{SHORT}:" in _fmt(_prose(ctx="untyped"), _opts("id"))
        assert f"{{AGENT:{SHORT}:" in _fmt(_prose(ctx="untyped"), _opts("auto"), "agents-untyped")
        assert f"{{AGENT:{SHORT}:" in _fmt(_prose(ctx="untyped"), _opts("auto-id"), "agents-untyped")
        out = _fmt(_prose(ctx="untyped"), _opts("never"))
        assert "{AGENT: report text }" in out and SHORT not in out

    def test_the_full_id_is_never_on_a_line(self):
        for mode in MODES:
            for channel in ("sesslog", "agents-untyped", "convo"):
                assert FULL not in _fmt(_prose(ctx="untyped"), _opts(mode), channel), (mode, channel)
                assert FULL not in _fmt(_tool(ctx=""), _opts(mode), channel), (mode, channel)


# ============================================================================
# The config surface: merge, schema, docs, and the untouched default
# ============================================================================

class TestConfigSurface:
    def test_merge_accepts_the_id_modes_and_ignores_others(self, monkeypatch, tmp_path):
        import cclogger.debug as dbg
        monkeypatch.setattr(dbg, "UNKNOWN_COLLECT_KEY_WARN_DIR", tmp_path)
        from cclogger.config_merge import apply_override_channel_options
        from cclogger.models import ChannelOptions
        opts = ChannelOptions()
        apply_override_channel_options(opts, {"agent_label": "id"}, "t")
        assert opts.agent_label == "id"
        apply_override_channel_options(opts, {"agent_label": "auto-id"}, "t")
        assert opts.agent_label == "auto-id"
        apply_override_channel_options(opts, {"agent_label": "with-id"}, "t")
        assert opts.agent_label == "auto-id"  # unknown value ignored
        apply_override_channel_options(opts, {"agent_label": None}, "t")
        assert opts.agent_label == "always"

    def test_the_modes_tuples_agree(self):
        from cclogger.models import AGENT_LABEL_AUTO_MODES, AGENT_LABEL_ID_MODES, AGENT_LABEL_MODES
        assert set(AGENT_LABEL_ID_MODES) <= set(AGENT_LABEL_MODES)
        assert set(AGENT_LABEL_AUTO_MODES) <= set(AGENT_LABEL_MODES)
        assert set(AGENT_LABEL_MODES) == set(MODES)

    def test_schema_enum_matches_the_code(self):
        from cclogger.models import AGENT_LABEL_MODES
        schema = json.loads((REPO / "hooks" / "schemas" / "session-logger.schema.json").read_text(encoding="utf-8"))

        def find(node):
            if isinstance(node, dict):
                if "agent_label" in node and isinstance(node["agent_label"], dict):
                    return node["agent_label"]
                for v in node.values():
                    hit = find(v)
                    if hit:
                        return hit
            elif isinstance(node, list):
                for v in node:
                    hit = find(v)
                    if hit:
                        return hit
            return None

        block = find(schema)
        assert block is not None
        assert block["enum"] == list(AGENT_LABEL_MODES)
        assert "a7c41e0b" in block["description"] and "[id" in block["description"]

    def test_docs_carry_the_row_and_the_recipe(self):
        text = (REPO / "docs" / "configuration.md").read_text(encoding="utf-8")
        assert '`"auto-id"`' in text
        assert "### Tell concurrent agents apart" in text
        assert "[id a7c41e0b9d2f53e18]" in text

    def test_the_shipped_default_is_untouched(self):
        from cclogger.models import AGENT_LABEL_ID_MODES, ChannelOptions, _default_channels
        assert ChannelOptions().agent_label == "always"
        for name, ch in _default_channels().items():
            assert ch.options.agent_label not in AGENT_LABEL_ID_MODES, name
