"""Per-channel `exclude` predicate (unit U3, 2026-09-02 incident) -- the
subtractive mirror of `collect`.

Maintainer decision (verbatim, 2026-09-02): "If we are going to allow users
to 'hide' a scope we should do so at each respective level where the user
CHOOSES to hide, a person can choose to hide it from the convo, they can
choose to hide it from the individual channels ... I'd say in general we
should by default INCLUDE the untyped entries in BOTH the convo and channel."

Grammar (same as collect): `exclude: {attribute: true | [values]}` on any
channel's options. Attribute-generic (AC-10 spirit), evaluated after routing
+ collection + subtype expansion; exclude beats collect; derived
`<base>-<subtype>` channels inherit the base's exclude unless declared
themselves; unknown keys warn once and are ignored; default: none.

Design: 2026-09-02__16-03-52__dev-workflow-process__untyped-subagent-bucketing-and-reconciliation-gating.md
(project-private; Addendum 3 decision 2, AC-5).
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
GUID = "e0c1ude0-0902-4bbb-8ccc-0000000000c3"
USER = "excluser"
TS = datetime(2026, 9, 3, 2, 0, 0)


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for k in ("CLAUDE_DIR", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


@pytest.fixture
def fresh(isolated_home):
    """(logger, config) with default channels in an isolated home."""
    from cclogger.logger import SessionLogger
    from cclogger.models import Config, SessionContext
    session = SessionContext(shell_type="bash.exe", session_name="excl-unit",
                             session_id=GUID, username=USER)
    config = Config()
    logger = SessionLogger(config, session, TS)
    return logger, config


def _agent_entry(ctx, agent_id="a0000000000000e1", text="REPORT"):
    from cclogger.models import LogEntry
    return LogEntry(raw_content=text, role="agent", tool_name="SubagentStop",
                    timestamp=TS, agent_context=ctx, agent_id=agent_id)


def _user_entry(text="USER-PROMPT"):
    from cclogger.models import LogEntry
    return LogEntry(raw_content=text, role="user", tool_name="UserPromptSubmit", timestamp=TS)


def _log(logger, entry, category="message_agent", tool="SubagentStop"):
    logger.log_entry(entry, tool_name=tool, tool_category=category,
                     event_time=TS, raw_json={})


def _text(d: Path, glob: str) -> str:
    files = list(d.glob(glob))
    return "".join(p.read_text(encoding="utf-8", errors="replace") for p in files)


# ============================================================================
# Merge / validation (mirror of TestCollectMerge)
# ============================================================================

class TestExcludeMerge:
    def _merged(self, override, monkeypatch, tmp_path):
        import cclogger.debug as dbg
        monkeypatch.setattr(dbg, "UNKNOWN_EXCLUDE_KEY_WARN_DIR", tmp_path / "warn")
        from cclogger.config_merge import apply_override_channel_options
        from cclogger.models import ChannelOptions
        opts = ChannelOptions()
        apply_override_channel_options(opts, {"exclude": override}, "convo")
        return opts.exclude

    def test_list_form_round_trips(self, monkeypatch, tmp_path):
        assert self._merged({"agent_context": ["untyped"]}, monkeypatch, tmp_path) == \
            {"agent_context": ["untyped"]}

    def test_true_form(self, monkeypatch, tmp_path):
        assert self._merged({"agent_context": True}, monkeypatch, tmp_path) == {"agent_context": True}

    def test_list_form_filters_non_strings(self, monkeypatch, tmp_path):
        assert self._merged({"agent_context": ["untyped", 7, None]}, monkeypatch, tmp_path) == \
            {"agent_context": ["untyped"]}

    def test_unknown_key_ignored_and_warned_once(self, monkeypatch, tmp_path):
        assert self._merged({"no_such_attr": True}, monkeypatch, tmp_path) is None
        self._merged({"no_such_attr": True}, monkeypatch, tmp_path)
        sentinels = list((tmp_path / "warn").glob("*.warned"))
        assert len(sentinels) == 1, sentinels

    def test_distinct_unknown_keys_get_distinct_sentinels(self, monkeypatch, tmp_path):
        """Kills mutant M6 (sanitizer negation dropped): two different unknown
        keys must produce two sentinels, i.e. two warnings."""
        self._merged({"nope_alpha": True}, monkeypatch, tmp_path)
        self._merged({"nope_beta": True}, monkeypatch, tmp_path)
        sentinels = sorted(p.name for p in (tmp_path / "warn").glob("*.warned"))
        assert sentinels == ["nope_alpha.warned", "nope_beta.warned"], sentinels

    def test_unknown_key_warns_exactly_once(self, monkeypatch, tmp_path):
        """Kills mutant M5 (early return -> pass): the debug line fires once,
        not on every occurrence."""
        import cclogger.debug as dbg
        calls = []
        monkeypatch.setattr(dbg, "debug_log", lambda msg: calls.append(msg))
        self._merged({"nope_gamma": True}, monkeypatch, tmp_path)
        self._merged({"nope_gamma": True}, monkeypatch, tmp_path)
        assert len([c for c in calls if "Unknown exclude key" in c]) == 1, calls

    def test_none_resets_and_false_yields_none(self, monkeypatch, tmp_path):
        assert self._merged(None, monkeypatch, tmp_path) is None
        assert self._merged({"agent_context": False}, monkeypatch, tmp_path) is None

    def test_default_is_no_exclusion_anywhere(self):
        from cclogger.models import Config
        for name, ch in Config().routing.channels.items():
            assert ch.options.exclude is None, name


# ============================================================================
# Evaluator semantics (in-process, isolated home)
# ============================================================================

class TestExcludeEvaluator:
    def test_exclude_on_convo_hides_untyped_there_only(self, fresh):
        logger, config = fresh
        config.routing.channels["convo"].options.exclude = {"agent_context": ["untyped"]}
        _log(logger, _agent_entry("untyped", text="UNTYPED-REPORT"))
        d = logger.session_dir
        assert "UNTYPED-REPORT" not in _text(d, ".convo_*")
        assert "UNTYPED-REPORT" in _text(d, ".sesslog_*")          # never-drop
        assert "UNTYPED-REPORT" in _text(d, ".agents-untyped_*")   # agents untouched

    def test_exclude_beats_collect_on_the_agents_channel(self, fresh):
        logger, config = fresh
        config.routing.channels["agents"].options.exclude = {"agent_context": ["untyped"]}
        _log(logger, _agent_entry("untyped", text="UNTYPED-REPORT"))
        _log(logger, _agent_entry("Explore", agent_id="a0000000000000e2", text="TYPED-REPORT"))
        d = logger.session_dir
        assert list(d.glob(".agents-untyped_*")) == []
        assert "UNTYPED-REPORT" not in _text(d, ".agents_*")
        assert "TYPED-REPORT" in _text(d, ".agents-explore_*")     # collect still works
        assert "UNTYPED-REPORT" in _text(d, ".convo_*")             # only agents hides it

    def test_derived_channels_inherit_the_base_exclude(self, fresh):
        logger, config = fresh
        config.routing.channels["agents"].options.exclude = {"agent_context": True}
        _log(logger, _agent_entry("Explore", text="TYPED-REPORT"))
        d = logger.session_dir
        assert list(d.glob(".agents-*")) == []
        assert "TYPED-REPORT" not in _text(d, ".agents_*")
        assert "TYPED-REPORT" in _text(d, ".sesslog_*")

    def test_true_form_never_touches_entries_without_the_attribute(self, fresh):
        logger, config = fresh
        config.routing.channels["convo"].options.exclude = {"agent_context": True}
        _log(logger, _user_entry("USER-PROMPT"), category="message_user", tool="UserPromptSubmit")
        _log(logger, _agent_entry("Explore", text="TYPED-REPORT"))
        convo = _text(logger.session_dir, ".convo_*")
        assert "USER-PROMPT" in convo and "TYPED-REPORT" not in convo

    def test_matching_is_normalized_both_sides(self, fresh):
        logger, config = fresh
        config.routing.channels["convo"].options.exclude = {"agent_context": ["EXPLORE"]}
        _log(logger, _agent_entry("Explore", text="TYPED-REPORT"))
        assert "TYPED-REPORT" not in _text(logger.session_dir, ".convo_*")

    def test_evaluator_is_attribute_generic(self, fresh, monkeypatch):
        """AC-10 rehearsal for exclude: a second axis needs a recognized-keys
        entry and an emission-side attribute, never an evaluator edit."""
        import cclogger.models as models
        monkeypatch.setattr(models, "EXCLUDE_RECOGNIZED_KEYS",
                            set(models.EXCLUDE_RECOGNIZED_KEYS) | {"tool_name"})
        logger, config = fresh
        config.routing.channels["convo"].options.exclude = {"tool_name": ["subagentstop"]}
        _log(logger, _agent_entry("Explore", text="TYPED-REPORT"))
        _log(logger, _user_entry("USER-PROMPT"), category="message_user", tool="UserPromptSubmit")
        convo = _text(logger.session_dir, ".convo_*")
        assert "TYPED-REPORT" not in convo and "USER-PROMPT" in convo


# ============================================================================
# End to end through the real hook with a user config file
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


class TestExcludeEndToEnd:
    def test_user_config_hides_untyped_from_convo_only(self, tmp_path):
        home = tmp_path / "home"
        (home / ".claude" / "plugins" / "settings").mkdir(parents=True)
        (home / ".claude" / "plugins" / "settings" / "session-logger.json").write_text(json.dumps({
            "routing": {"channels": {"convo": {"options": {"exclude": {"agent_context": ["untyped"]}}}}}
        }), encoding="utf-8")
        transcript = home / "t.jsonl"
        transcript.write_text('{"type":"user"}\n', encoding="utf-8")
        base = {"session_id": GUID, "transcript_path": str(transcript),
                "cwd": "/", "permission_mode": "default"}
        events = [dict(base, hook_event_name="SessionStart", source="startup")]
        for i in range(3):
            events.append(dict(base, hook_event_name="SubagentStop",
                               agent_id=f"a{i:016x}", agent_type="", stop_hook_active=False,
                               agent_transcript_path=str(home / "missing.jsonl"),
                               last_assistant_message=f"UNTYPED-MSG-{i}"))
        events.append(dict(base, hook_event_name="SubagentStop",
                           agent_id="a0000000000000ff", agent_type="Explore", stop_hook_active=False,
                           agent_transcript_path=str(transcript),
                           last_assistant_message="TYPED-REPORT-MARKER"))
        _drive_hook(home, events)
        d = next(iter((home / ".claude" / "sesslogs").glob("*")))
        convo = _text(d, ".convo_*")
        assert "UNTYPED-MSG-" not in convo
        assert "TYPED-REPORT-MARKER" in convo
        assert _text(d, ".sesslog_*").count("UNTYPED-MSG-") == 3
        assert _text(d, ".agents-untyped_*").count("UNTYPED-MSG-") == 3
