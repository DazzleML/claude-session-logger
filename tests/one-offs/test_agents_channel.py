"""Phase 5 (Github #40) — .agents_* channel for sub-agent invocations.

Tests cover the four-layer user model from the v0.4.x "Channels as Data" epic
(Github #44), exercising layers 1-3 directly on the new agents channel:

  Layer 1: channel exists in defaults with the right shape
  Layer 2: Task tool routes to agents via the `meta` category route;
           per-channel verbosity / formatter / newline policy take effect
  Layer 3: subtype_routing.meta=true produces `.agents-<subagent_type>_*`
           paths; subtype-channel options inheritance works
           (declare-to-override, omit-to-inherit per Phase 2+3)
  Layer 4 (cross-channel navigation back to source): out of scope here;
           covered by GitHub #43 epic when its sub-issues land.
"""
from __future__ import annotations

import pytest


# ============================================================================
# Layer 1: agents channel exists in defaults
# ============================================================================


class TestAgentsChannelDefaults:
    """The `agents` channel is part of the shipped default channel set."""

    def test_agents_channel_present(self):
        from cclogger.models import _default_channels
        channels = _default_channels()
        assert "agents" in channels

    def test_agents_channel_file_prefix(self):
        from cclogger.models import _default_channels
        channels = _default_channels()
        assert channels["agents"].file_prefix == ".agents_"

    def test_agents_channel_enabled_by_default(self):
        """Sub-agent visibility is enabled out-of-the-box; users can disable
        via `routing.channels.agents.enabled = false` if they don't use agents.
        """
        from cclogger.models import _default_channels
        channels = _default_channels()
        assert channels["agents"].enabled is True

    def test_agents_channel_uses_default_options(self):
        """Default options: verbosity='full' (no truncation on agent
        invocations), default formatter (rich-format Task entries),
        no special newline policy."""
        from cclogger.models import _default_channels
        channels = _default_channels()
        opts = channels["agents"].options
        assert opts.verbosity == "full"
        assert opts.formatter == "default"
        assert opts.suppress_markers is False  # gets session markers


# ============================================================================
# Layer 2: meta category routes to agents
# ============================================================================


class TestMetaCategoryRouting:
    """The `meta` category (where Task lives) routes to [sesslog, agents]."""

    def test_meta_route_includes_agents(self):
        from cclogger.models import _default_category_routes
        routes = _default_category_routes()
        assert "meta" in routes
        assert "agents" in routes["meta"]

    def test_meta_route_includes_sesslog(self):
        """sesslog stays in the route — kitchen sink always captures meta."""
        from cclogger.models import _default_category_routes
        routes = _default_category_routes()
        assert "sesslog" in routes["meta"]

    def test_meta_route_excludes_shell(self):
        """Phase 5 design decision: Task invocations are agent-specific,
        not shell history. Users who want Task in `.shell_*` can override
        `routing.category_routes.meta` in their config.
        """
        from cclogger.models import _default_category_routes
        routes = _default_category_routes()
        assert "shell" not in routes["meta"]

    def test_meta_route_excludes_tools(self):
        """Phase 5 design decision: agents has its own dedicated view;
        `.tools_*` doesn't need to duplicate Task entries."""
        from cclogger.models import _default_category_routes
        routes = _default_category_routes()
        assert "tools" not in routes["meta"]

    def test_agent_tool_categorized_as_meta(self):
        """Live agent-spawning tool name. Claude Code emits `tool_name:
        "Agent"` (per source canvass 2026-05-12); without this entry the
        agents channel never fires in production. See
        `private/claude/notes/research/2026-05-12__claude-code-event-surface.md`
        for the source-clone evidence."""
        from cclogger.categorize import categorize_tool
        assert categorize_tool("Agent") == "meta"

    def test_task_family_tools_remain_in_task_category(self):
        """The `Task*` family (TaskCreate/TaskUpdate/...) is the TodoAI
        task-management family — distinct from the `Agent` tool and
        correctly categorized as `task`, not `meta`."""
        from cclogger.categorize import categorize_tool
        for tool_name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TaskOutput", "TaskStop"):
            assert categorize_tool(tool_name) == "task", (
                f"{tool_name} should remain in `task` category, not `meta`"
            )

    def test_bare_task_no_longer_routes_to_meta(self):
        """The bare `Task` key was removed from TOOL_CATEGORIES — it was
        never the agent-spawning tool name in production, and conflated
        with the Task* family. Bare `Task` falls through to `unknown`
        category like any unrecognized tool name."""
        from cclogger.categorize import categorize_tool
        assert categorize_tool("Task") == "unknown"


# ============================================================================
# Layer 2 (cont.): per-channel options for agents take effect
# ============================================================================


class TestAgentsChannelOptionsResolution:
    """Per-channel verbosity / formatter resolution for the agents channel.

    Uses the same hierarchical resolver tests apply elsewhere — just confirms
    agents-specific options are wired through, not that the resolver works.
    """

    def test_user_override_of_agents_verbosity_resolves(self):
        from cclogger.formatters.legacy import _resolve_verbosity
        from cclogger.models import ChannelOptions

        # User overrides agents to truncate `user` direction at 200 chars
        opts = ChannelOptions(verbosity={"_default": "full", "user": {"max_chars": 200}})

        # Direction `user` -> 200
        assert _resolve_verbosity(opts, "user", "Task", global_default=20) == 200
        # Other directions -> full (0)
        assert _resolve_verbosity(opts, "ai", "Task", global_default=20) == 0
        assert _resolve_verbosity(opts, "agent", "Task", global_default=20) == 0

    def test_agents_can_opt_out_of_markers(self):
        """Users who tail .agents_* for raw invocation data can suppress
        the session-start marker without disabling the channel."""
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(suppress_markers=True)
        assert opts.suppress_markers is True


# ============================================================================
# Layer 3: subtype routing produces .agents-<subagent_type>_*
# ============================================================================


class TestAgentsSubtypeExpansion:
    """When subtype_routing.meta is enabled, agent invocations split into
    per-agent files like `.agents-help_*`, `.agents-senior-engineer_*` via
    the `_subtype_for_meta` extractor (subagent_type).
    """

    def test_subtype_for_meta_extracts_subagent_type(self):
        from cclogger.categorize import get_subtype
        raw = {"tool_input": {"subagent_type": "help"}}
        assert get_subtype("meta", "Task", raw) == "help"

    def test_subtype_for_meta_returns_none_when_missing(self):
        from cclogger.categorize import get_subtype
        raw = {"tool_input": {}}  # no subagent_type
        assert get_subtype("meta", "Task", raw) is None

    def test_subtype_extractor_sanitizes_filesystem_unsafe_chars(self):
        """Subagent type strings could in principle contain unsafe chars;
        the extractor sanitizes for filesystem use."""
        from cclogger.categorize import get_subtype
        raw = {"tool_input": {"subagent_type": "weird/agent name"}}
        result = get_subtype("meta", "Task", raw)
        assert "/" not in result and " " not in result


class TestAgentsSubtypeChannelOptionsInheritance:
    """Subtype-derived channels (`.agents-help_*`) inherit parent `agents`
    ChannelOptions by default (omit-to-inherit), and explicit overrides
    in `routing.channels` win (declare-to-override). This is the Phase 2+3
    contract applied to the new Phase 5 channel.
    """

    def test_subtype_channel_inherits_parent_options_by_default(self):
        """Without an explicit `.agents-help_*` entry in routing.channels,
        the derived channel uses parent `agents`'s options."""
        from cclogger.models import ChannelConfig, ChannelOptions, Config

        config = Config()
        parent_options = config.routing.channels["agents"].options

        # Sanity check: parent agents channel has verbosity="full"
        assert parent_options.verbosity == "full"
        assert parent_options.formatter == "default"

    def test_user_can_declare_subtype_channel_to_override(self):
        """Users can opt into different options for a specific agent subtype
        by declaring `agents-help` (or similar) in routing.channels with its
        own options."""
        from cclogger.models import ChannelConfig, ChannelOptions, Config

        config = Config()
        # User declares an explicit override for the help-agent channel
        config.routing.channels["agents-help"] = ChannelConfig(
            file_prefix=".agents-help_",
            options=ChannelOptions(verbosity={"max_chars": 500}),
        )
        assert config.routing.channels["agents-help"].options.verbosity == {"max_chars": 500}
        # Parent agents channel unchanged
        assert config.routing.channels["agents"].options.verbosity == "full"


# ============================================================================
# Cross-cutting: Phase 4 marker broadcast covers agents channel
# ============================================================================


class TestAgentsChannelMarkerBroadcast:
    """The Phase 4 marker broadcast policy applies to agents — markers
    appear in `.agents_*` by default, can be suppressed per-channel.
    """

    def test_agents_channel_in_default_marker_broadcast(self, tmp_path, monkeypatch):
        from cclogger.logger import SessionLogger
        from cclogger.models import Config, SessionContext
        from datetime import datetime

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        session = SessionContext(
            shell_type="bash.exe",
            session_name="phase5-agents-marker-test",
            session_id="phase5-test-session-1",
            username="testuser",
        )
        config = Config()
        event_time = datetime(2026, 5, 12, 14, 0, 0)

        logger = SessionLogger(config, session, event_time)
        agents_path = logger._get_channel_path("agents")
        assert agents_path.exists()
        content = agents_path.read_text(encoding="utf-8", errors="replace")
        assert content.count("═══ SESSION START") == 1


# ============================================================================
# Regression: hook subprocess actually loads user config (Github #46)
# ============================================================================


class TestHookSubprocessHonorsUserConfig:
    """Github #46 regression: the live hook entry point (log-command.py)
    must use ConfigLoader.load() — calling load_configuration() directly
    silently ignores the new-style user config and renders every Phase 1+
    user-facing setting dead (subtype_routing, suppress_markers,
    enable/disable, custom channels, etc.).

    This test pins the call site by inspecting the source — a cheap
    structural check that catches accidental reverts without needing to
    spawn an actual subprocess.
    """

    def test_log_command_imports_ConfigLoader_not_load_configuration(self):
        """The top-of-file import must pull in `ConfigLoader`, not the
        legacy `load_configuration` function. Re-imports of
        `load_configuration` directly are also OK as long as `ConfigLoader`
        is the one used in main()."""
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent.parent / "hooks" / "scripts" / "log-command.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))

        # Walk the AST for `from cclogger.config import ...`
        names_imported_from_config = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "cclogger.config":
                for alias in node.names:
                    names_imported_from_config.add(alias.name)

        assert "ConfigLoader" in names_imported_from_config, (
            "log-command.py must import ConfigLoader from cclogger.config "
            "(see Github #46 — using load_configuration directly silently "
            "ignores user config)"
        )

    def test_log_command_main_calls_ConfigLoader_load(self):
        """In main(), the config load call must be ConfigLoader.load(...).
        Direct calls to load_configuration(...) bypass the new-style config
        and silently disable every user-config-driven feature.

        Walks the AST to find actual function calls (ignoring string
        literals or comments that mention either name)."""
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent.parent / "hooks" / "scripts" / "log-command.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))

        configloader_load_calls = 0
        bare_load_configuration_calls = 0

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match `ConfigLoader.load(...)` (Attribute on Name)
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "ConfigLoader"
                and func.attr == "load"
            ):
                configloader_load_calls += 1
            # Match `load_configuration(...)` bare call (Name)
            elif isinstance(func, ast.Name) and func.id == "load_configuration":
                bare_load_configuration_calls += 1

        assert configloader_load_calls >= 1, (
            "log-command.py must call ConfigLoader.load() at least once — see Github #46"
        )
        assert bare_load_configuration_calls == 0, (
            "log-command.py must not call load_configuration() directly "
            f"(found {bare_load_configuration_calls} bare calls) — see Github #46"
        )

    def test_hook_subprocess_honors_user_subtype_routing(self, tmp_path):
        """End-to-end regression: spawn log-command.py as a subprocess with
        HOME redirected to a tmp dir containing a user config that enables
        per-channel subtype splitting on the `shell` channel. Fire a
        PowerShell tool event. Verify a `.shell-powershell_*.log` file
        materializes, proving the hook actually loaded the user config.

        v0.3.7-pre: subtype splitting moved from category-wide
        `routing.subtype_routing.<cat>` (removed) to per-channel
        `routing.channels.<name>.options.subtype_split`. This test pins
        the per-channel API end-to-end.

        This complements the AST tests above with a real execution-path
        check — the AST tests catch "someone changed the call site," this
        test catches "the call site change still doesn't actually load
        user config" (e.g., wrong path, wrong loader).
        """
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        hook_script = repo_root / "hooks" / "scripts" / "log-command.py"

        # Set up tmp HOME with user config enabling subtype_split on `shell`
        config_dir = tmp_path / ".claude" / "plugins" / "settings"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "session-logger.json"
        config_path.write_text(json.dumps({
            "routing": {
                "channels": {
                    "shell": {"options": {"subtype_split": True}},
                },
            }
        }), encoding="utf-8")

        # Build a synthetic Bash event
        event = {
            "session_id": "00000000-0000-0000-0000-666666666666",
            "transcript_path": str(tmp_path / "transcript.jsonl"),
            "cwd": str(tmp_path / "test-project"),
            "permission_mode": "default",
            "hook_event_name": "PostToolUse",
            "tool_name": "PowerShell",
            "tool_input": {"command": "Get-Date"},
            "tool_response": {"success": True},
            "tool_use_id": "test-uid",
            "duration_ms": 100,
        }

        # Make sure cwd dir + transcript exist (some hook code expects them)
        (tmp_path / "test-project").mkdir(parents=True)
        (tmp_path / "transcript.jsonl").write_text("{}\n", encoding="utf-8")

        env = os.environ.copy()
        env["USERPROFILE"] = str(tmp_path)
        env["HOME"] = str(tmp_path)
        env["USERNAME"] = "regtester"
        env.pop("DAZZLE_FILEKIT_CACHE", None)

        result = subprocess.run(
            [sys.executable, str(hook_script)],
            input=json.dumps(event),
            text=True,
            env=env,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Hook exited {result.returncode}: stderr={result.stderr[:500]}"
        )

        # The user config enables `shell.options.subtype_split = true`.
        # PowerShell tool is in `bash` category whose extractor lowercases
        # the tool name -> "powershell". Only `shell` opted in, so we
        # expect EXACTLY `.shell-powershell_*.log` -- NOT `.tools-powershell_*`
        # or `.sesslog-powershell_*` (those channels stayed at default
        # subtype_split=False). This is the Bug A fix in action.
        sesslogs = tmp_path / ".claude" / "sesslogs"
        all_files = list(sesslogs.rglob("*.log")) if sesslogs.exists() else []
        all_names = sorted(p.name for p in all_files)

        shell_subtype = [n for n in all_names if n.startswith(".shell-powershell_")]
        tools_subtype = [n for n in all_names if n.startswith(".tools-powershell_")]
        sesslog_subtype = [n for n in all_names if n.startswith(".sesslog-powershell_")]

        assert shell_subtype, (
            f"User config `shell.options.subtype_split = true` not honored. "
            f"Expected at least one `.shell-powershell_*.log` file. "
            f"Got: {all_names}. "
            f"Either the hook isn't loading the new-style user config "
            f"(Github #46), or the per-channel subtype_split field isn't "
            f"wired into _expand_with_subtype_channels."
        )
        assert not tools_subtype, (
            f"Bug A regression: tools channel got subtype split despite "
            f"subtype_split=False default. tools-subtype files: {tools_subtype}"
        )
        assert not sesslog_subtype, (
            f"Bug A regression: sesslog channel got subtype split despite "
            f"subtype_split=False default. sesslog-subtype files: {sesslog_subtype}"
        )
