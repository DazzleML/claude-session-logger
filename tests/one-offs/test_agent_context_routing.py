"""#53 agent-context-aware routing: the .agents-<type>_* file carries the
agent's full story (dispatch + attributed internal tool calls + final report).

Design: 2026-08-13__10-42-19__issue-53-agent-context-routing-design.md
(project-private) -- acceptance checks AC-1..AC-10. Spike-validated 5/5 before
implementation (tests/one-offs/thinking/spike_53_agent_context_routing.py).

Fixture facts (learned by the spike's red phase):
  - the dispatch tool is named "Agent" (not "Task") in current Claude Code;
  - split semantics write collected entries to BOTH the base .agents_ file
    and the .agents-<type>_ sibling.
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
GUID = "ac53e2e0-53aa-4bbb-8ccc-c0011ec70001"
USER = "ctxuser"


# ============================================================================
# Fixtures (mirrors test_marker_broadcast.py isolation pattern)
# ============================================================================

@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


@pytest.fixture
def fresh_logger(isolated_home):
    """(logger, config) with default channels in an isolated home."""
    from cclogger.logger import SessionLogger
    from cclogger.models import Config, SessionContext

    session = SessionContext(
        shell_type="bash.exe",
        session_name="ac53-unit",
        session_id=f"unit-{id(isolated_home)}",
        username=USER,
    )
    config = Config()
    logger = SessionLogger(config, session, datetime(2026, 8, 13, 12, 0, 0))
    return logger, config


def _entry(**kw):
    from cclogger.models import LogEntry
    defaults = dict(raw_content="x", role="bash", tool_name="Bash",
                    timestamp=datetime(2026, 8, 13, 12, 0, 0))
    defaults.update(kw)
    return LogEntry(**defaults)


# ============================================================================
# AC-2: the discriminator -- agent_id presence, not agent_type
# ============================================================================

class TestDiscriminator:
    def _ctx(self, payload):
        from cclogger.models import ToolInfo
        base = {"tool_name": "Bash", "tool_input": {"command": "x"},
                "session_id": GUID}
        base.update(payload)
        return ToolInfo.from_json(base).agent_context

    def test_agent_id_plus_type_yields_context(self):
        assert self._ctx({"agent_id": "a1", "agent_type": "Explore"}) == "Explore"

    def test_agent_type_alone_is_not_subagent(self):
        # The --agent shape: main thread carries agent_type WITHOUT agent_id.
        # Verbatim platform fact turned test (AC-2).
        assert self._ctx({"agent_type": "Explore"}) is None

    def test_agent_id_alone_falls_back_to_id(self):
        assert self._ctx({"agent_id": "a1"}) == "a1"

    def test_plain_main_session_none(self):
        assert self._ctx({}) is None

    def test_legacy_speculative_fields_no_longer_match(self):
        # Pre-#53 detection walked these names; none appear in real payloads
        # and 'subagent_type' top-level would have mislabeled anything
        # carrying it. Deleted, not deprecated.
        assert self._ctx({"subagent_type": "X", "parent_agent": "Y",
                          "spawned_by": "Z"}) is None


# ============================================================================
# AC-3 (normalization half): one choke point, lowercase + sanitize + cap
# ============================================================================

class TestNormalizeSubtype:
    def test_lowercases(self):
        from cclogger.categorize import normalize_subtype
        assert normalize_subtype("Explore") == "explore"

    def test_underscores_become_hyphens(self):
        from cclogger.categorize import normalize_subtype
        assert normalize_subtype("my_snake_agent") == "my-snake-agent"

    def test_byte_cap_applies(self):
        from cclogger.categorize import normalize_subtype
        from cclogger.session_naming import SUBTYPE_MAX_BYTES
        out = normalize_subtype("X" * 500)
        assert out is not None
        assert len(out.encode("utf-8")) <= SUBTYPE_MAX_BYTES

    def test_empty_and_none_yield_none(self):
        from cclogger.categorize import normalize_subtype
        assert normalize_subtype("") is None
        assert normalize_subtype(None) is None
        assert normalize_subtype("___") is None  # sanitizes to nothing

    def test_get_subtype_meta_now_lowercases(self):
        from cclogger.categorize import get_subtype
        out = get_subtype("meta", "Agent",
                          {"tool_input": {"subagent_type": "Explore"}})
        assert out == "explore"


# ============================================================================
# AC-7: config surface -- merge round-trip, unknown keys warn-once + ignored
# ============================================================================

class TestCollectMerge:
    def _merged(self, override, monkeypatch, tmp_path):
        import cclogger.debug as dbg
        monkeypatch.setattr(dbg, "UNKNOWN_COLLECT_KEY_WARN_DIR",
                            tmp_path / "warns")
        from cclogger.config_merge import apply_override_channel_options
        from cclogger.models import ChannelOptions
        opts = ChannelOptions()
        apply_override_channel_options(opts, override, "testchan")
        return opts

    def test_true_form_round_trips(self, monkeypatch, tmp_path):
        opts = self._merged({"collect": {"agent_context": True}},
                            monkeypatch, tmp_path)
        assert opts.collect == {"agent_context": True}

    def test_list_form_filters_non_strings(self, monkeypatch, tmp_path):
        opts = self._merged({"collect": {"agent_context": ["oracle", 42]}},
                            monkeypatch, tmp_path)
        assert opts.collect == {"agent_context": ["oracle"]}

    def test_unknown_key_ignored_not_fatal(self, monkeypatch, tmp_path):
        # Config written for a NEWER plugin version degrades gracefully.
        opts = self._merged(
            {"collect": {"agent_context": True, "spawn_depth": True}},
            monkeypatch, tmp_path)
        assert opts.collect == {"agent_context": True}
        # warn-once sentinel dropped
        assert (tmp_path / "warns" / "spawn_depth.warned").exists()

    def test_none_resets(self, monkeypatch, tmp_path):
        opts = self._merged({"collect": None}, monkeypatch, tmp_path)
        assert opts.collect is None

    def test_false_value_yields_no_predicate(self, monkeypatch, tmp_path):
        opts = self._merged({"collect": {"agent_context": False}},
                            monkeypatch, tmp_path)
        assert opts.collect is None

    def test_agents_default_ships_collect_on(self):
        from cclogger.models import _default_channels
        assert _default_channels()["agents"].options.collect == \
            {"agent_context": True}


# ============================================================================
# AC-1 core + AC-4: the evaluator -- generic, per-channel, additive
# ============================================================================

class TestCollectEvaluator:
    def test_agents_collects_agent_context_entry(self, fresh_logger):
        logger, _ = fresh_logger
        got = logger._collect_channels_for_entry(_entry(agent_context="Explore"))
        assert got == {"agents": "explore"}  # value normalized = the subtype

    def test_no_context_no_collection(self, fresh_logger):
        logger, _ = fresh_logger
        assert logger._collect_channels_for_entry(_entry()) == {}

    def test_plain_string_entry_never_matches(self, fresh_logger):
        logger, _ = fresh_logger
        assert logger._collect_channels_for_entry("transitional string") == {}

    def test_list_form_filters_and_is_case_insensitive(self, fresh_logger):
        logger, config = fresh_logger
        config.routing.channels["agents"].options.collect = \
            {"agent_context": ["Oracle"]}  # capital in config
        assert logger._collect_channels_for_entry(
            _entry(agent_context="oracle")) == {"agents": "oracle"}
        assert logger._collect_channels_for_entry(
            _entry(agent_context="Explore")) == {}

    def test_any_channel_can_collect(self, fresh_logger):
        # AC-4: the mechanism is generic -- a non-agents channel declared in
        # config collects too; no channel name is special-cased in code.
        from cclogger.models import ChannelConfig, ChannelOptions
        logger, config = fresh_logger
        config.routing.channels["mywatch"] = ChannelConfig(
            file_prefix=".mywatch_",
            options=ChannelOptions(collect={"agent_context": True}),
        )
        got = logger._collect_channels_for_entry(_entry(agent_context="Explore"))
        assert got["mywatch"] == "explore"
        assert got["agents"] == "explore"


# ============================================================================
# AC-10: second-axis rehearsal -- a new axis is a whitelist entry + attribute
# ============================================================================

class TestSecondAxisRehearsal:
    def test_new_axis_needs_zero_evaluator_changes(self, fresh_logger,
                                                   monkeypatch, tmp_path):
        """Whitelist a second LogEntry attribute ('role') and collect by it.

        This test IS the enforcement of the extensibility promise: if a
        future edit hardcodes 'agent_context' inside the evaluator, this
        goes red. (User challenge 2026-08-13: "We actually tested that?")
        """
        import cclogger.debug as dbg
        import cclogger.models as models
        from cclogger.config_merge import apply_override_channel_options
        from cclogger.models import ChannelConfig, ChannelOptions

        monkeypatch.setattr(dbg, "UNKNOWN_COLLECT_KEY_WARN_DIR",
                            tmp_path / "warns")
        monkeypatch.setattr(models, "COLLECT_RECOGNIZED_KEYS",
                            models.COLLECT_RECOGNIZED_KEYS | {"role"})
        # config_merge imported the set by value? No -- it imports the name
        # at module load; patch there too so the merge validates it.
        import cclogger.config_merge as cm
        monkeypatch.setattr(cm, "COLLECT_RECOGNIZED_KEYS",
                            cm.COLLECT_RECOGNIZED_KEYS | {"role"})

        logger, config = fresh_logger
        config.routing.channels["roleview"] = ChannelConfig(
            file_prefix=".roleview_", options=ChannelOptions())
        apply_override_channel_options(
            config.routing.channels["roleview"].options,
            {"collect": {"role": ["user"]}}, "roleview")

        got = logger._collect_channels_for_entry(_entry(role="user"))
        assert got.get("roleview") == "user"
        assert logger._collect_channels_for_entry(
            _entry(role="bash")).get("roleview") is None


# ============================================================================
# Disabled-channel suppression covers derived siblings (tester finding P3)
# ============================================================================

class TestDisabledChannelSuppression:
    def test_disabling_agents_suppresses_subtype_siblings(self, isolated_home):
        """`enabled: false` on a base channel must suppress its derived
        `.agents-<type>_*` files too -- the pre-fix literal-only lookup
        treated every derived name as enabled (found by the independent
        tester pass, probe P3)."""
        from cclogger.logger import SessionLogger
        from cclogger.models import Config, SessionContext

        session = SessionContext(shell_type="bash.exe",
                                 session_name="p3-suppress",
                                 session_id="p3-suppress-0001",
                                 username=USER)
        config = Config()
        config.routing.channels["agents"].enabled = False
        logger = SessionLogger(config, session, datetime(2026, 8, 13, 12, 0, 0))
        logger.log_entry(_entry(agent_context="Explore",
                                raw_content="echo p3"),
                         tool_name="Bash", tool_category="bash",
                         raw_json={"tool_name": "Bash",
                                   "tool_input": {"command": "echo p3"}})
        agents_files = list(logger.session_dir.glob(".agents*"))
        assert agents_files == [], agents_files


# ============================================================================
# AC-3 (source half): collected channels split by the ENTRY's attribute
# ============================================================================

class TestSubtypeSourceRule:
    def test_collected_channel_splits_by_context_not_category(self, fresh_logger):
        logger, _ = fresh_logger
        raw = {"tool_name": "Bash", "tool_input": {"command": "x"}}
        out = logger._expand_with_subtype_channels(
            ["shell", "sesslog", "agents"], "Bash", "bash", raw,
            collect_sources={"agents": "explore"},
        )
        assert "agents-explore" in out
        assert "agents-bash" not in out  # category subtype must NOT leak in

    def test_category_channels_keep_category_subtype(self, fresh_logger):
        logger, config = fresh_logger
        config.routing.channels["shell"].options.subtype_split = True
        raw = {"tool_name": "Bash", "tool_input": {"command": "x"}}
        out = logger._expand_with_subtype_channels(
            ["shell", "agents"], "Bash", "bash", raw,
            collect_sources={"agents": "explore"},
        )
        assert "shell-bash" in out
        assert "agents-explore" in out

    def test_guard_fix_no_category_extractor_still_expands_collected(self, fresh_logger):
        # Pre-#53 the expander returned early when the category yielded no
        # subtype -- a Read call inside an agent (io category, no extractor)
        # would never have expanded the agents channel. Spike-surfaced.
        logger, _ = fresh_logger
        raw = {"tool_name": "Read", "tool_input": {"file_path": "x"}}
        out = logger._expand_with_subtype_channels(
            ["sesslog", "agents"], "Read", "io", raw,
            collect_sources={"agents": "explore"},
        )
        assert "agents-explore" in out

    def test_no_sources_no_subtype_unchanged(self, fresh_logger):
        logger, _ = fresh_logger
        raw = {"tool_name": "Read", "tool_input": {"file_path": "x"}}
        out = logger._expand_with_subtype_channels(
            ["sesslog", "agents"], "Read", "io", raw)
        assert out == ["sesslog", "agents"]


# ============================================================================
# E2E through the real hook subprocess (AC-1, AC-5, AC-8)
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


def _events(transcript: Path, with_agent: bool = True) -> list:
    base = {"session_id": GUID, "transcript_path": str(transcript),
            "cwd": "/ac53-e2e", "permission_mode": "default"}
    evs = [dict(base, hook_event_name="SessionStart", source="startup")]
    if not with_agent:
        for i in range(2):
            evs.append(dict(base, hook_event_name="PostToolUse",
                            tool_name="Bash",
                            tool_input={"command": f"echo plain-{i}"},
                            tool_response={"stdout": "", "stderr": "",
                                           "interrupted": False}))
        return evs
    evs.append(dict(base, hook_event_name="PostToolUse", tool_name="Agent",
                    tool_input={"subagent_type": "Explore",
                                "prompt": "e2e probe", "description": "e2e"},
                    tool_response={"status": "launched"}))
    for i in range(3):
        evs.append(dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                        agent_id="agentE2E0001", agent_type="Explore",
                        tool_input={"command": f"echo inner-{i}"},
                        tool_response={"stdout": "", "stderr": "",
                                       "interrupted": False}))
    evs.append(dict(base, hook_event_name="PostToolUse", tool_name="Bash",
                    agent_type="Explore",  # --agent shape: NO agent_id
                    tool_input={"command": "echo main-thread-not-agent"},
                    tool_response={"stdout": "", "stderr": "",
                                   "interrupted": False}))
    evs.append(dict(base, hook_event_name="SubagentStop",
                    agent_id="agentE2E0001", agent_type="Explore",
                    stop_hook_active=False,
                    agent_transcript_path=str(transcript),
                    last_assistant_message="REPORT-53-MARKER findings text"))
    return evs


def _session_dir(home: Path) -> Path:
    dirs = list((home / ".claude" / "sesslogs").glob("*"))
    assert len(dirs) == 1, dirs
    return dirs[0]


def _read(f: Path) -> str:
    return f.read_text(encoding="utf-8", errors="replace")


class TestEndToEndFullStory:
    def test_agents_file_carries_dispatch_calls_and_report(self, tmp_path):
        """AC-1: dispatch + attributed internal calls + final report, in the
        lowercase .agents-explore_* file; --agent shape excluded; original
        channels unchanged (additive)."""
        home = tmp_path / "home"
        home.mkdir()
        transcript = home / "t.jsonl"
        transcript.write_text('{"type":"user"}\n', encoding="utf-8")
        _drive_hook(home, _events(transcript))
        d = _session_dir(home)

        sub = list(d.glob(".agents-explore_*"))
        assert len(sub) == 1, list(d.glob(".agents*"))
        text = _read(sub[0])
        assert text.count("{Agent") == 1          # dispatch (subtype now lc)
        assert text.count("{Bash|Explore") == 3   # attributed internal calls
        assert "REPORT-53-MARKER" in text         # final report collected
        assert "main-thread-not-agent" not in text  # AC-2 in the pipeline

        base = _read(next(iter(d.glob(".agents_*"))))
        assert base.count("{Bash|Explore") == 3   # split writes base + sibling

        # Additivity: original channels keep everything
        shell = _read(next(iter(d.glob(".shell_*"))))
        assert shell.count("echo inner-") == 3
        assert "main-thread-not-agent" in shell
        convo = _read(next(iter(d.glob(".convo_*"))))
        assert "REPORT-53-MARKER" in convo        # report still reaches convo

    def test_agent_free_session_untouched(self, tmp_path):
        """AC-8 shape: no agent traffic -> no subtype files, no Bash in agents."""
        home = tmp_path / "home"
        home.mkdir()
        transcript = home / "t.jsonl"
        transcript.write_text('{"type":"user"}\n', encoding="utf-8")
        _drive_hook(home, _events(transcript, with_agent=False))
        d = _session_dir(home)
        assert list(d.glob(".agents-*")) == []
        agents_files = list(d.glob(".agents_*"))
        if agents_files:  # base may exist via marker broadcast
            assert "{Bash" not in _read(agents_files[0])

    def test_three_restart_stability_and_legacy_adoption(self, tmp_path):
        """AC-5: legacy capital-case sibling seeded; three runs; filename set
        stable (no growth loop), nothing quarantined to baks/."""
        home = tmp_path / "home"
        home.mkdir()
        transcript = home / "t.jsonl"
        transcript.write_text('{"type":"user"}\n', encoding="utf-8")
        _drive_hook(home, _events(transcript))
        d = _session_dir(home)
        # Seed a legacy capital-case file the way pre-#53 wrote it
        lower = next(iter(d.glob(".agents-explore_*")))
        legacy = d / lower.name.replace(".agents-explore_", ".agents-Explore_")
        if not legacy.exists():  # on Windows this aliases `lower` itself
            legacy.write_text(_read(lower), encoding="utf-8")

        _drive_hook(home, _events(transcript))
        names_run2 = sorted(p.name for p in d.glob(".agents*"))
        _drive_hook(home, _events(transcript))
        names_run3 = sorted(p.name for p in d.glob(".agents*"))

        assert names_run2 == names_run3          # no churn, no --NNN growth
        assert not (d / "baks").exists()          # nothing quarantined
        assert not any("--0" in n for n in names_run3)


# ============================================================================
# #50 + #55: agent-label rendering modes (always | auto | never)
# ============================================================================

class TestAgentLabelModes:
    def _fmt(self, channel_name, opts, entry):
        from cclogger.formatters import format_for_channel
        from cclogger.models import Config
        return format_for_channel(entry, opts, channel_name, Config())

    def _tool_entry(self, ctx="Explore"):
        # Shaped like generate_entry output: dual-rendered legacy strings
        from cclogger.models import LogEntry
        return LogEntry(
            raw_content="echo hi",
            role="bash",
            metadata={
                "_legacy_complete": '[[2026-08-13 12:00:00]] {Bash|Explore: echo hi }',
                "_legacy_complete_plain": '[[2026-08-13 12:00:00]] {Bash: echo hi }',
                "summary_plain": None,
            },
            timestamp=datetime(2026, 8, 13, 12, 0, 0),
            tool_name="Bash",
            agent_context=ctx,
        )

    def _agent_report(self, ctx="Explore"):
        from cclogger.models import LogEntry
        return LogEntry(raw_content="report text", role="agent",
                        tool_name="SubagentStop",
                        timestamp=datetime(2026, 8, 13, 12, 0, 0),
                        agent_context=ctx)

    def _opts(self, mode):
        from cclogger.models import ChannelOptions
        return ChannelOptions(agent_label=mode)

    def test_always_keeps_tool_suffix(self):
        out = self._fmt("sesslog", self._opts("always"), self._tool_entry())
        assert "{Bash|Explore:" in out

    def test_never_drops_tool_suffix(self):
        out = self._fmt("sesslog", self._opts("never"), self._tool_entry())
        assert "{Bash:" in out and "|Explore" not in out

    def test_auto_drops_only_when_redundant_with_subtype(self):
        # In .agents-explore_* the suffix repeats the filename -> dropped
        out = self._fmt("agents-explore", self._opts("auto"), self._tool_entry())
        assert "|Explore" not in out
        # In sesslog the identity is load-bearing -> kept
        out = self._fmt("sesslog", self._opts("auto"), self._tool_entry())
        assert "{Bash|Explore:" in out

    def test_agent_role_identity_in_chat(self):
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(formatter="chat", agent_label="always")
        out = self._fmt("convo", opts, self._agent_report())
        assert "AGENT:explore" in out  # normalized, matches file naming

    def test_agent_role_identity_in_default_channels(self):
        out = self._fmt("sesslog", self._opts("always"), self._agent_report())
        assert "{AGENT:explore:" in out

    def test_agent_role_identity_suppressed_by_never(self):
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(formatter="chat", agent_label="never")
        out = self._fmt("convo", opts, self._agent_report())
        assert "AGENT" in out and ":explore" not in out

    def test_auto_suppresses_identity_in_matching_subtype_file(self):
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(formatter="chat", agent_label="auto")
        out = self._fmt("agents-explore", opts, self._agent_report())
        assert ":explore" not in out

    def test_merge_and_default(self, monkeypatch, tmp_path):
        import cclogger.debug as dbg
        monkeypatch.setattr(dbg, "UNKNOWN_COLLECT_KEY_WARN_DIR", tmp_path)
        from cclogger.config_merge import apply_override_channel_options
        from cclogger.models import ChannelOptions
        opts = ChannelOptions()
        assert opts.agent_label == "always"  # snapshot-stable default (#55)
        apply_override_channel_options(opts, {"agent_label": "auto"}, "t")
        assert opts.agent_label == "auto"
        apply_override_channel_options(opts, {"agent_label": "bogus"}, "t")
        assert opts.agent_label == "auto"  # unknown value ignored
        apply_override_channel_options(opts, {"agent_label": None}, "t")
        assert opts.agent_label == "always"

    def test_dual_render_variants_from_real_generation(self):
        # generate_entry bakes both variants when context present
        from cclogger.formatters.legacy import generate_entry
        from cclogger.models import Config, ToolInfo
        ti = ToolInfo.from_json({
            "tool_name": "Bash", "tool_input": {"command": "echo x"},
            "session_id": GUID, "agent_id": "a1", "agent_type": "Explore",
        })
        entry = generate_entry(ti, Config(), "echo x",
                               datetime(2026, 8, 13, 12, 0, 0))
        lc = entry.metadata["_legacy_complete"]
        plain = entry.metadata["_legacy_complete_plain"]
        assert "Bash|Explore" in lc and "Bash|Explore" not in plain
        assert plain.replace("{Bash:", "{Bash|Explore:") == lc  # only the label differs
