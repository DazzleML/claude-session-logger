"""Untyped-subagent bucketing (2026-09-02 incident): Claude Code's internal
transcript-less side-queries stop with an `agent_id` and an EMPTY
`agent_type`; the classifier for that class is the fixed bucket "untyped",
the id travels on the entry line, and the agents channel writes ONE feed
file (`.agents-untyped_*`) instead of one file per stop.

Design: 2026-09-02__16-03-52__dev-workflow-process__untyped-subagent-bucketing-and-reconciliation-gating.md
(project-private; Addendum 3 = final unit list). Investigation:
2026-09-02__14-44-55__investigate__untyped-agent-spam-and-quadratic-reconciliation-timeout.md.
Graduated from tests/one-offs/thinking/repro_agent_spam_and_timeout.py (Probe A).

Acceptance checks covered here: AC-1 (bounded by construction), AC-3 (typed
path unchanged), AC-6 (never-drop: every untyped message reaches .sesslog,
.convo and the untyped feed under the default policy).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO / "hooks" / "scripts" / "log-command.py"
GUID = "b0c4e7ed-0902-4bbb-8ccc-0000000000a1"
USER = "untypeduser"
ID_FILE = re.compile(r"^\.agents-a[0-9a-f]{16}_")


# ============================================================================
# The resolver (pure function; dazzle-loglib export candidate)
# ============================================================================

class TestResolveAgentIdentity:
    def _r(self, payload):
        from cclogger.models import resolve_agent_identity
        return resolve_agent_identity(payload)

    def test_typed_subagent(self):
        assert self._r({"agent_id": "a1", "agent_type": "Explore"}) == ("Explore", "a1")

    def test_empty_type_is_untyped_bucket_with_id_kept(self):
        assert self._r({"agent_id": "a000e885b41c764eb", "agent_type": ""}) == \
            ("untyped", "a000e885b41c764eb")

    def test_whitespace_and_none_types_are_untyped(self):
        assert self._r({"agent_id": "a1", "agent_type": "  "})[0] == "untyped"
        assert self._r({"agent_id": "a1", "agent_type": None})[0] == "untyped"
        assert self._r({"agent_id": "a1"})[0] == "untyped"

    def test_agent_type_without_id_is_main_thread(self):
        # --agent session shape (#53 AC-2): never subagent context.
        assert self._r({"agent_type": "Explore"}) == (None, None)

    def test_plain_payload(self):
        assert self._r({}) == (None, None)

    def test_id_is_stringified_and_type_stripped(self):
        assert self._r({"agent_id": 12345, "agent_type": " oracle "}) == ("oracle", "12345")

    def test_toolinfo_carries_both(self):
        from cclogger.models import ToolInfo
        ti = ToolInfo.from_json({"tool_name": "Bash", "tool_input": {},
                                 "session_id": GUID, "agent_id": "a1",
                                 "agent_type": ""})
        assert (ti.agent_context, ti.agent_id) == ("untyped", "a1")


# ============================================================================
# E2E through the real hook subprocess (AC-1, AC-3, AC-6)
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
        proc = subprocess.run([sys.executable, str(HOOK_SCRIPT)],
                              input=json.dumps(ev).encode("utf-8"),
                              capture_output=True, env=env, timeout=30)
        assert proc.returncode == 0, proc.stderr.decode()[:800]


def _base(transcript: Path) -> dict:
    return {"session_id": GUID, "transcript_path": str(transcript),
            "cwd": "/", "permission_mode": "default"}


def _untyped_stop(base: dict, i: int, home: Path) -> dict:
    # 17 hex with the real ids' constant leading `a`; the counter sits in the
    # first 8 characters because that is all a label shows (unit 7, 2026-09-03)
    return dict(base, hook_event_name="SubagentStop",
                agent_id=f"a{i:07x}000000000", agent_type="",
                stop_hook_active=False,
                agent_transcript_path=str(home / "never-written.jsonl"),
                last_assistant_message=f"UNTYPED-MSG-{i:03d} verifying step {i}")


def _session_dir(home: Path) -> Path:
    dirs = list((home / ".claude" / "sesslogs").glob("*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def _read(f: Path) -> str:
    return f.read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def driven_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    transcript = home / "t.jsonl"
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    base = _base(transcript)
    events = [dict(base, hook_event_name="SessionStart", source="startup"),
              dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                   tool_input={"command": "echo warm"},
                   tool_response={"stdout": "warm", "stderr": "", "interrupted": False})]
    events += [_untyped_stop(base, i, home) for i in range(50)]
    # control: SubagentStop shape with NO agent_id -> not subagent context
    events.append(dict(base, hook_event_name="SubagentStop", agent_type="",
                       stop_hook_active=False,
                       last_assistant_message="CONTROL-NO-AGENT-ID"))
    # the TOOL-CALL leg (hypothetical for untyped agents -- none of 1,530
    # observed ids ever made one -- but the legacy pass-through must carry
    # classifier and id the right way round; mutation M12 hid here)
    events.append(dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                       agent_id="af00d000000000000", agent_type="",
                       tool_input={"command": "echo UNTYPED-TOOL-CALL"},
                       tool_response={"stdout": "", "stderr": "", "interrupted": False}))
    events.append(dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                       agent_id="a0000000000000ff", agent_type="Explore",
                       tool_input={"command": "echo TYPED-TOOL-CALL"},
                       tool_response={"stdout": "", "stderr": "", "interrupted": False}))
    # a typed agent alongside, to prove the typed path is untouched (AC-3)
    events.append(dict(base, hook_event_name="SubagentStop",
                       agent_id="a0000000000000ff", agent_type="Explore",
                       stop_hook_active=False,
                       agent_transcript_path=str(transcript),
                       last_assistant_message="TYPED-REPORT-MARKER"))
    _drive_hook(home, events)
    return home


class TestEndToEndBucketing:
    def test_fifty_untyped_stops_make_one_feed_file(self, driven_home):
        """AC-1: bounded by construction -- one .agents-untyped_* file, fifty
        attributed lines, zero id-named files."""
        d = _session_dir(driven_home)
        id_files = [p for p in d.iterdir() if ID_FILE.match(p.name)]
        assert id_files == [], [p.name for p in id_files]
        feed = list(d.glob(".agents-untyped_*"))
        assert len(feed) == 1, [p.name for p in d.iterdir()]
        text = _read(feed[0])
        assert text.count("UNTYPED-MSG-") == 50
        # every line attributed to its instance: AGENT:untyped/<id> -- the
        # id in its 8-character label form (unit 7, 2026-09-03), never the
        # full 17
        ids = re.findall(r"AGENT:untyped/(a[0-9a-f]{7})(?![0-9a-f])", text)
        assert len(ids) == 50 and len(set(ids)) == 50
        assert not re.search(r"untyped/a[0-9a-f]{16}", text)
        assert "CONTROL-NO-AGENT-ID" not in text
        assert "TYPED-REPORT-MARKER" not in text

    def test_tool_call_leg_carries_classifier_and_id_the_right_way_round(self, driven_home):
        """Legacy pass-through (kills mutant M12): an in-agent tool call from an
        untyped agent lands in the untyped feed with `Bash|untyped/<id>`; the
        typed one lands in .agents-explore_* with the classic `Bash|Explore`."""
        d = _session_dir(driven_home)
        feed = _read(next(iter(d.glob(".agents-untyped_*"))))
        assert "{Bash|untyped/af00d000: echo UNTYPED-TOOL-CALL" in feed  # 8-char label form
        assert "echo TYPED-TOOL-CALL" not in feed  # ("TYPED-" is a substring of "UNTYPED-")
        typed = _read(next(iter(d.glob(".agents-explore_*"))))
        assert "{Bash|Explore: echo TYPED-TOOL-CALL" in typed
        assert "a0000000000000ff" not in typed  # typed labels never grow an id

    def test_typed_agent_path_unchanged(self, driven_home):
        """AC-3: the typed agent still gets its own lowercase file and label."""
        d = _session_dir(driven_home)
        typed = list(d.glob(".agents-explore_*"))
        assert len(typed) == 1
        text = _read(typed[0])
        assert "TYPED-REPORT-MARKER" in text
        assert "AGENT:explore" in text and "untyped" not in text

    def test_never_drop_default_policy(self, driven_home):
        """AC-6: default policy INCLUDES untyped entries in .sesslog and .convo
        (maintainer decision 2026-09-02: 'by default INCLUDE the untyped
        entries in BOTH the convo and channel')."""
        d = _session_dir(driven_home)
        sesslog = _read(next(iter(d.glob(".sesslog_*"))))
        convo = _read(next(iter(d.glob(".convo_*"))))
        assert sesslog.count("UNTYPED-MSG-") == 50
        assert convo.count("UNTYPED-MSG-") == 50
        assert convo.count("AGENT:untyped/") == 50
        # the base agents file receives collected entries too (split writes
        # base + sibling -- fixture fact from the #53 spike)
        base = _read(next(iter(d.glob(".agents_*"))))
        assert base.count("UNTYPED-MSG-") == 50

    def test_directory_stays_small(self, driven_home):
        """Growth bound: 50 untyped stops add exactly one file to the dir."""
        d = _session_dir(driven_home)
        names = sorted(p.name for p in d.iterdir() if p.is_file())
        agents = [n for n in names if n.startswith(".agents")]
        # .agents_ (base), .agents-untyped_, .agents-explore_ -- nothing else
        assert len(agents) == 3, agents


# ============================================================================
# Label rendering: the id is the attribution (AC-1 line shape, #50/#55 modes)
# ============================================================================

class TestUntypedLabel:
    ID = "a000e885b41c764eb"
    SHORT = ID[:8]  # the label form (unit 7, 2026-09-03): labels never show the full id

    def _fmt(self, channel_name, opts, entry):
        from cclogger.formatters import format_for_channel
        from cclogger.models import Config
        return format_for_channel(entry, opts, channel_name, Config())

    def _report(self, ctx="untyped", agent_id=ID):
        from cclogger.models import LogEntry
        return LogEntry(raw_content="verifying step", role="agent",
                        tool_name="SubagentStop",
                        timestamp=datetime(2026, 9, 2, 12, 0, 0),
                        agent_context=ctx, agent_id=agent_id)

    def test_chat_always_shows_class_and_id(self):
        from cclogger.models import ChannelOptions
        out = self._fmt("convo", ChannelOptions(formatter="chat", agent_label="always"),
                        self._report())
        assert f"AGENT:untyped/{self.SHORT}" in out and self.ID not in out

    def test_default_channel_shows_class_and_id(self):
        from cclogger.models import ChannelOptions
        out = self._fmt("sesslog", ChannelOptions(agent_label="always"), self._report())
        assert f"{{AGENT:untyped/{self.SHORT}:" in out and self.ID not in out

    def test_auto_in_untyped_feed_keeps_only_the_id(self):
        # The filename already says "untyped"; the id is the only attribution
        # the line can carry, so `auto` keeps it (unlike typed agents, where
        # auto drops the whole identity inside .agents-<type>_*).
        from cclogger.models import ChannelOptions
        out = self._fmt("agents-untyped",
                        ChannelOptions(formatter="chat", agent_label="auto"),
                        self._report())
        assert f"AGENT:{self.SHORT}" in out
        assert "untyped/" not in out

    def test_never_drops_identity(self):
        from cclogger.models import ChannelOptions
        out = self._fmt("convo", ChannelOptions(formatter="chat", agent_label="never"),
                        self._report())
        assert "AGENT" in out and self.SHORT not in out and "untyped" not in out

    def test_untyped_without_id_is_still_bucketed(self):
        from cclogger.models import ChannelOptions
        out = self._fmt("convo", ChannelOptions(formatter="chat", agent_label="always"),
                        self._report(agent_id=None))
        assert "AGENT:untyped" in out and "untyped/" not in out

    def test_typed_agent_label_unchanged(self):
        # AC-3: typed identity never grows an id suffix.
        from cclogger.models import ChannelOptions
        out = self._fmt("convo", ChannelOptions(formatter="chat", agent_label="always"),
                        self._report(ctx="Explore", agent_id="a0000000000000ff"))
        assert "AGENT:explore" in out and "a0000000000000ff" not in out
