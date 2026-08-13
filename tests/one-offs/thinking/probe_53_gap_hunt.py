"""#53 gap-hunt probes -- independent of the inline mutation matrix.

Exploratory verification for the tester-unbounded checklist run
(v0.3.11__Feature__issue-53-agent-context-routing.md, step 3). These are
NOT part of the shipped test suite -- they're throwaway probes to check
edge cases the mutation matrix structurally cannot exercise (mutation
testing proves the EXISTING assertions are load-bearing; it says nothing
about behavior nobody asserted on yet).

Five probes, per the dispatch brief:
  P1 -- agent_context that normalizes to None (all-illegal-char raw value)
  P2 -- collect list-form with an empty list
  P3 -- a channel with collect declared but enabled=false
  P4 -- Agent dispatch payload with subagent_type missing entirely
  P5 -- duplicate SubagentStop events (idempotency of report entries)

Run: python -m pytest tests/one-offs/thinking/probe_53_gap_hunt.py -v -s
Isolation: same pattern as test_agent_context_routing.py -- subprocess
hook invocations get HOME/USERPROFILE redirected to tmp_path; unit-level
probes use SessionLogger against a tmp_path session dir directly. Nothing
here touches the real ~/.claude tree or the live repo source.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = REPO / "hooks" / "scripts" / "log-command.py"
GUID = "ac53e2e0-53aa-4bbb-8ccc-c0011ec70099"
USER = "probeuser"

sys.path.insert(0, str(REPO / "hooks" / "scripts"))


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


def _session_dir(home: Path) -> Path:
    dirs = list((home / ".claude" / "sesslogs").glob("*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def _read(f: Path) -> str:
    return f.read_text(encoding="utf-8", errors="replace")


def _base(transcript: Path) -> dict:
    return {"session_id": GUID, "transcript_path": str(transcript),
            "cwd": "/probe53", "permission_mode": "default"}


# ============================================================================
# P1 -- agent_context that normalizes to None
# ============================================================================

def test_p1_illegal_char_agent_type_drops_from_agents_channel(tmp_path):
    """normalize_subtype('___') == None (categorize.py: all three chars are
    non-alnum, collapse to a single '-', then rstrip('-.') empties it).
    Trace through _collect_channels_for_entry: raw='___' is truthy, so the
    `if not raw: continue` guard does NOT fire -- but the very next guard
    `if not normalized: continue` DOES fire once normalize_subtype returns
    None. Net effect: the agents channel's collect predicate silently
    never matches for this entry. Question: does that mean the entry is
    dropped from the agents channel ENTIRELY (base + subtype), even though
    a normal agent's calls land in both?"""
    home = tmp_path / "home"
    home.mkdir()
    transcript = home / "t.jsonl"
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    b = _base(transcript)
    events = [
        dict(b, hook_event_name="SessionStart", source="startup"),
        dict(b, hook_event_name="PostToolUse", tool_name="Agent",
             tool_input={"subagent_type": "___", "prompt": "p1", "description": "p1"},
             tool_response={"status": "launched"}),
        dict(b, hook_event_name="PostToolUse", tool_name="Bash",
             agent_id="agentP1", agent_type="___",
             tool_input={"command": "echo p1-inner"},
             tool_response={"stdout": "", "stderr": "", "interrupted": False}),
    ]
    _drive_hook(home, events)
    d = _session_dir(home)

    subtype_files = list(d.glob(".agents-*"))
    base_files = list(d.glob(".agents_*"))
    shell = _read(next(iter(d.glob(".shell_*"))))

    print(f"\nP1: subtype files = {[f.name for f in subtype_files]}")
    print(f"P1: base agents files = {[f.name for f in base_files]}")
    print(f"P1: 'p1-inner' in shell channel = {'echo p1-inner' in shell}")
    if base_files:
        base_text = _read(base_files[0])
        print(f"P1: 'p1-inner' in base .agents_ file = {'p1-inner' in base_text}")
        print(f"P1: dispatch marker in base .agents_ file = {'{Agent' in base_text}")

    # The inner Bash call is ALWAYS present in shell (category route,
    # unaffected by collect). This is the control assertion.
    assert "echo p1-inner" in shell


# ============================================================================
# P2 -- collect list-form with an empty list
# ============================================================================

def test_p2_empty_list_collect_never_matches(tmp_path):
    """{'agent_context': []} -- does empty-list mean 'collect nothing'
    (vacuous, defensible) or does it accidentally behave like True?"""
    sys.path.insert(0, str(REPO / "hooks" / "scripts"))
    from cclogger.logger import SessionLogger
    from cclogger.models import Config, SessionContext, LogEntry

    home = tmp_path / "home2"
    home.mkdir()
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)

    session = SessionContext(shell_type="bash.exe", session_name="p2",
                              session_id="p2-session", username=USER)
    config = Config()
    config.routing.channels["agents"].options.collect = {"agent_context": []}
    logger = SessionLogger(config, session, datetime(2026, 8, 13, 12, 0, 0))

    entry = LogEntry(raw_content="x", role="bash", tool_name="Bash",
                      timestamp=datetime(2026, 8, 13, 12, 0, 0),
                      agent_context="explore")
    result = logger._collect_channels_for_entry(entry)
    print(f"\nP2: collect_sources for agent_context='explore' with collect=[] -> {result}")
    assert result == {}, f"expected no match for empty-list collect, got {result}"


# ============================================================================
# P3 -- channel with collect declared but enabled=false
# ============================================================================

def test_p3_disabled_channel_with_collect_and_subtype_split(tmp_path):
    """agents channel: enabled=False, but options.collect and
    options.subtype_split both still True (user disabled the channel but
    didn't clear its options -- plausible real config). log_entry()'s
    write loop checks `channel and not channel.enabled` keyed by exact
    channel_name. For the literal 'agents' channel_name that correctly
    skips. But _collect_channels_for_entry() doesn't check .enabled at
    all, and the derived 'agents-explore' channel_name is NOT a key in
    routing.channels (only 'agents' is), so channels.get('agents-explore')
    returns None -- and `if channel and not channel.enabled` is False
    when channel is None. Question: does the derived subtype file get
    written anyway, even though the base channel is disabled?"""
    sys.path.insert(0, str(REPO / "hooks" / "scripts"))
    from cclogger.logger import SessionLogger
    from cclogger.models import Config, SessionContext, LogEntry

    home = tmp_path / "home3"
    home.mkdir()
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)

    session = SessionContext(shell_type="bash.exe", session_name="p3",
                              session_id="p3-session", username=USER)
    config = Config()
    config.routing.channels["agents"].enabled = False
    logger = SessionLogger(config, session, datetime(2026, 8, 13, 12, 0, 0))

    entry = LogEntry(raw_content="echo p3", role="bash", tool_name="Bash",
                      timestamp=datetime(2026, 8, 13, 12, 0, 0),
                      agent_context="explore")
    logger.log_entry(entry, tool_name="Bash", tool_category="bash",
                      event_time=datetime(2026, 8, 13, 12, 0, 0),
                      raw_json={"tool_name": "Bash", "tool_input": {}})

    d = logger.session_dir
    base_files = list(d.glob(".agents_*"))
    subtype_files = list(d.glob(".agents-*"))
    print(f"\nP3: base .agents_ files (channel disabled) = {[f.name for f in base_files]}")
    print(f"P3: .agents-explore subtype files (channel disabled) = {[f.name for f in subtype_files]}")
    if subtype_files:
        print(f"P3: subtype file content = {_read(subtype_files[0])!r}")

    # Record actual behavior either way -- this is a discovery probe, not
    # an assertion of the "correct" answer (that's a design judgment call).


# ============================================================================
# P4 -- Agent dispatch payload with subagent_type missing entirely
# ============================================================================

def test_p4_dispatch_missing_subagent_type(tmp_path):
    """tool_input has no 'subagent_type' key at all (not empty string --
    ABSENT). _subtype_for_meta does tool_input.get('subagent_type') or
    None -> None. get_subtype -> normalize_subtype(None) -> None (the
    `if not value: return None` guard at the top). Expect: dispatch entry
    lands in base .agents_ only, no crash, no subtype file from this
    event alone."""
    home = tmp_path / "home4"
    home.mkdir()
    transcript = home / "t.jsonl"
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    b = _base(transcript)
    events = [
        dict(b, hook_event_name="SessionStart", source="startup"),
        dict(b, hook_event_name="PostToolUse", tool_name="Agent",
             tool_input={"prompt": "p4 no subagent_type key", "description": "p4"},
             tool_response={"status": "launched"}),
    ]
    _drive_hook(home, events)
    d = _session_dir(home)

    base_files = list(d.glob(".agents_*"))
    subtype_files = list(d.glob(".agents-*"))
    print(f"\nP4: base .agents_ files = {[f.name for f in base_files]}")
    print(f"P4: subtype files (should be none from this event) = {[f.name for f in subtype_files]}")
    assert base_files, "dispatch entry should still land in base .agents_ file"
    assert "{Agent" in _read(base_files[0])


# ============================================================================
# P5 -- duplicate SubagentStop events
# ============================================================================

def test_p5_duplicate_subagent_stop_report_idempotency(tmp_path):
    """Fire the identical SubagentStop payload twice. conversation.py's
    handler has no dedup/sentinel -- every call appends via atomic_append.
    Expect (and record): the report marker appears twice, not once."""
    home = tmp_path / "home5"
    home.mkdir()
    transcript = home / "t.jsonl"
    transcript.write_text('{"type":"user"}\n', encoding="utf-8")
    b = _base(transcript)
    stop_event = dict(b, hook_event_name="SubagentStop",
                       agent_id="agentP5", agent_type="Explore",
                       stop_hook_active=False,
                       agent_transcript_path=str(transcript),
                       last_assistant_message="REPORT-P5-MARKER unique text")
    events = [
        dict(b, hook_event_name="SessionStart", source="startup"),
        dict(b, hook_event_name="PostToolUse", tool_name="Agent",
             tool_input={"subagent_type": "Explore", "prompt": "p5", "description": "p5"},
             tool_response={"status": "launched"}),
        stop_event,
        stop_event,  # fired twice -- simulates duplicate delivery
    ]
    _drive_hook(home, events)
    d = _session_dir(home)

    sub = list(d.glob(".agents-explore_*"))
    convo = list(d.glob(".convo_*"))
    assert sub, "expected .agents-explore_* to exist"
    sub_text = _read(sub[0])
    convo_text = _read(convo[0]) if convo else ""
    sub_count = sub_text.count("REPORT-P5-MARKER")
    convo_count = convo_text.count("REPORT-P5-MARKER")
    print(f"\nP5: REPORT-P5-MARKER count in .agents-explore_ = {sub_count}")
    print(f"P5: REPORT-P5-MARKER count in .convo_ = {convo_count}")
    # Recording behavior, not asserting a "correct" answer -- duplicate
    # SubagentStop delivery is a platform question, not a #53 design goal.
