"""Entry framing: the frame's braces always match, the body stays verbatim.

Graduated from tests/one-offs/thinking/poc_convo_frame_ambiguity.py
(2026-09-03): the maintainer's own message, which contains an unbalanced
`{`, rendered as `[[ts]] {USER:\\n<body>\\n}` and left `{USER:` unmatched
for the editor brace jump (vim `%`, VS Code) the maintainer navigates
with; the live .convo_* held 24 such body braces.

The rule (design Addendum 4; docs/channels.md "Entry framing"): the body
is recorded verbatim; for every unmatched `{` in the body one `}` is
appended after the frame's closing brace (`}}}` = two strays), and for
every unmatched `}` one `{` is inserted after the frame's opening brace
(`{{USER:`). The frame's braces stay the outermost pair in every channel.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hooks" / "scripts"))

from cclogger import frame  # noqa: E402
from cclogger.formatters import format_for_channel  # noqa: E402
from cclogger.models import ChannelOptions, LogEntry, NewlinePolicy  # noqa: E402

TS = datetime(2026, 9, 3, 15, 0, 3)
PFX = "[[2026-09-03 15:00:03]] "
CONVO = ChannelOptions(verbosity="full", formatter="chat", newline_policy=NewlinePolicy.RENDER)
ESCAPE = ChannelOptions()
FILEIO = ChannelOptions(verbosity="full", newline_policy=NewlinePolicy.RENDER)
TASKS = ChannelOptions(formatter="task-only")

MAINTAINER_MSG = (
    "re:{\n"
    " So \"show five lines\" is not expressible in config today.\n"
    "}\n"
    "\n"
    "Otherwise ... we still had things to do:{\n"
    "re:{\n"
    "| Report-leg cursor bug | designed, not built |\n"
    "}\n"
    "\n"
    "Then after that we want our \"sesslog-main\"."
)
ENTRYLIKE_MSG = (
    "Look at this line from the log:\n"
    "[[2026-09-03 14:03:12]] {AI:\n"
    "some quoted narration\n"
    "}\n"
    "Notice the frame."
)
BODIES = {
    "stray-open": "things to do:{",
    "two-stray-open": "a { b { c",
    "stray-close": "oops }",
    "both-stray": "} and then {",
    "balanced": "re:{ x }",
    "nested-balanced": "f({a: {b: 1}})",
    "maintainer": MAINTAINER_MSG,
    "entry-like": ENTRYLIKE_MSG,
    "none": "plain prose",
}


def _entry(msg: str, role: str = "user") -> LogEntry:
    return LogEntry(raw_content=msg, role=role, timestamp=TS, tool_name="UserPromptSubmit")


def _render(msg: str, opts: ChannelOptions, role: str = "user", channel: str = "convo") -> str:
    return format_for_channel(_entry(msg, role), opts, channel)


# ---------------------------------------------------------------- frame.py

class TestStrayCounts:
    @pytest.mark.parametrize("text,expected", [
        ("plain", (0, 0)), ("re:{ x }", (0, 0)), ("f({a: {b: 1}})", (0, 0)), ("", (0, 0)),
        ("things to do:{", (1, 0)), ("a { b { c", (2, 0)), ("oops }", (0, 1)),
        ("} and then {", (1, 1)), ("}}{", (1, 2)), (MAINTAINER_MSG, (1, 0)), (ENTRYLIKE_MSG, (0, 0)),
    ])
    def test_counts(self, text, expected):
        assert frame.stray_counts(text) == expected


class TestPadFrame:
    def test_balanced_entry_is_the_same_object(self):
        e = PFX + "{USER: re:{ x } }"
        assert frame.pad_frame(e) is e

    def test_unclosed_body_braces_append_closers(self):
        assert frame.pad_frame(PFX + "{USER:\na { b { c\n}") == PFX + "{USER:\na { b { c\n}}}"

    def test_unopened_body_braces_prepend_openers(self):
        assert frame.pad_frame(PFX + "{USER:\noops }\n}") == PFX + "{{USER:\noops }\n}"

    def test_both_sides(self):
        assert frame.pad_frame(PFX + "{USER: } and then { }") == PFX + "{{USER: } and then { }}"

    def test_pwd_part_stays_after_the_padding(self):
        e = PFX + '{Bash: echo "{" } ["C:\\\\code"]'
        assert frame.pad_frame(e) == PFX + '{Bash: echo "{" }} ["C:\\\\code"]'

    def test_entries_without_the_frame_shape_are_untouched(self):
        for e in ("SESSION START {", PFX + "SESSION START {", "plain {", PFX + "{Bash: x } trailing {"):
            assert frame.pad_frame(e) == e

    def test_only_a_complete_pwd_part_may_follow_the_frame(self):
        """Kills M4 (and -> or in the pwd check): a tail that merely starts
        with ` ["` or merely ends with `"]` is not a pwd part, so the entry
        is not the frame shape and must be left alone."""
        for tail in (' [note "]', ' ["C:/x" and more', ' [FAILED: "x"]'):
            e = PFX + "{Bash: echo { }" + tail
            assert frame.pad_frame(e) == e, tail
        # the real pwd part still passes
        assert frame.pad_frame(PFX + '{Bash: echo { } ["C:/x"]') == PFX + '{Bash: echo { }} ["C:/x"]'

    def test_body_is_never_altered(self):
        for body in BODIES.values():
            out = frame.pad_frame(PFX + "{USER:\n" + body + "\n}")
            assert "\n" + body + "\n" in out

    def test_frame_is_matched_counts_like_an_editor(self):
        assert frame.frame_is_matched("{USER: a }")
        assert not frame.frame_is_matched("{USER: a { }")
        assert not frame.frame_is_matched("{USER: } a }")
        assert not frame.frame_is_matched("{USER: \\{ }")  # editors ignore backslashes
        assert frame.frame_is_matched("{USER: a { }}")
        assert frame.frame_is_matched("{{USER: } a }")


# --------------------------------------------- integrity through every shape

class TestFrameIntegrity:
    @pytest.mark.parametrize("name", list(BODIES))
    @pytest.mark.parametrize("opts,channel", [
        (CONVO, "convo"), (FILEIO, "fileio"), (ESCAPE, "sesslog"),
    ], ids=["chat-render", "default-render", "escape"])
    def test_frame_braces_always_pair(self, name, opts, channel):
        out = _render(BODIES[name], opts, channel=channel)
        assert frame.frame_is_matched(out), out

    @pytest.mark.parametrize("name", list(BODIES))
    def test_body_is_verbatim_in_render_channels(self, name):
        body = BODIES[name]
        assert "\n" + body + "\n" in _render(body, CONVO)
        assert body in _render(body, FILEIO, channel="fileio")

    @pytest.mark.parametrize("name", list(BODIES))
    def test_body_is_verbatim_modulo_newline_escape_in_escape_channels(self, name):
        body = BODIES[name].replace("\n", "\\n")
        full = ChannelOptions(verbosity="full")  # ESCAPE, no preview truncation
        assert body in _render(BODIES[name], full, channel="sesslog")

    @pytest.mark.parametrize("name", ["balanced", "nested-balanced", "none", "entry-like"])
    def test_balanced_bodies_get_no_extra_braces(self, name):
        body = BODIES[name]
        assert _render(body, CONVO) == PFX + "{USER:\n" + body + "\n}"

    def test_truncation_cannot_leave_the_frame_unmatched(self):
        """A preview cut inside a balanced pair is balanced outside the frame."""
        out = _render("re:{ a long balanced body }", ChannelOptions(verbosity={"max_chars": 6}), channel="sesslog")
        assert out == PFX + "{USER: re:{ a... }}"
        assert frame.frame_is_matched(out)


# -------------------------------------------------------- the shapes, exactly

class TestChatFrame:
    def test_shape_unchanged_for_balanced_bodies(self):
        assert _render("hello\nworld", CONVO) == PFX + "{USER:\nhello\nworld\n}"

    def test_maintainer_example_ends_with_the_extra_closer(self):
        out = _render(MAINTAINER_MSG, CONVO)
        assert out == PFX + "{USER:\n" + MAINTAINER_MSG + "\n}}"

    def test_two_unclosed_braces_end_with_three_closers(self):
        assert _render("a { b { c", CONVO).endswith("\na { b { c\n}}}")

    def test_unopened_brace_pads_the_opening_line(self):
        assert _render("oops }", CONVO) == PFX + "{{USER:\noops }\n}"

    def test_empty_body_unchanged_shape(self):
        assert _render("", CONVO, role="ai") == PFX + "{AI:\n\n}"

    def test_agent_label_keeps_frame(self):
        entry = LogEntry(raw_content="report {\nx", role="agent", timestamp=TS,
                         tool_name="SubagentStop", agent_context="explore", agent_id="a1")
        out = format_for_channel(entry, CONVO, "convo")
        assert out == PFX + "{AGENT:explore:\nreport {\nx\n}}"


class TestDefaultFormatterShapes:
    def test_template_entry_render(self):
        entry = LogEntry(raw_content="line one\nline two {\n", role="write", timestamp=TS,
                         tool_name="Write", summary='"C:/x/y.txt" ← {snippet} (3L)')
        out = format_for_channel(entry, FILEIO, "fileio")
        assert out == PFX + '{"C:/x/y.txt" ← line one\nline two {\n (3L) }}'

    def test_single_line_render_entry_unchanged(self):
        assert _render("one line", FILEIO, channel="fileio") == PFX + "{USER: one line }"

    def test_task_only_shape(self):
        entry = LogEntry(raw_content="", role="task-create", timestamp=TS, tool_name="TaskCreate",
                         metadata={"task_content": 'CREATE: "fix {"'})
        assert format_for_channel(entry, TASKS, "tasks") == PFX + '{CREATE: "fix {" }}'


class TestLegacyAssemblyPath:
    """Tool entries reach default channels through legacy.generate_entry's
    precomputed `_legacy_complete` string, returned as-is by the default
    formatter; padding happens at dispatch so it holds there too."""

    def _entry_for(self, command: str):
        from cclogger.formatters.legacy import generate_entry
        from cclogger.models import CommandContent, Config, ToolInfo
        info = ToolInfo(name="Bash", input={"command": command}, description="", session_id="s",
                        transcript_path="", raw_json={"tool_input": {"command": command}})
        cc = CommandContent(raw_content=command, legacy_string=command, summary_template=None)
        return generate_entry(info, Config(), cc, TS)

    def test_bash_command_with_stray_brace_is_framed_at_dispatch(self):
        out = format_for_channel(self._entry_for('echo "{"'), None, "shell")
        assert 'echo "{"' in out
        assert out.endswith('echo "{" }}') or out.endswith('echo "{" }}' + out[out.rfind(' ["'):])
        assert frame.frame_is_matched(out)

    def test_balanced_command_is_byte_identical(self):
        out = format_for_channel(self._entry_for("awk '{print $1}'"), None, "shell")
        assert "{Bash: awk '{print $1}' }" in out
        assert not out.endswith("}}")
