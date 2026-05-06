"""Tests: tools channel (v0.3.0).

Validates the new `tools` channel that captures AI activity (tools, skills,
tasks, shell commands) without prose -- the "find exact tool calls"
investigation view that the user's primary workflow depends on.

Closes #28. Source: 2026-05-01__17-36-55__channel-architecture-evolution-epic.md.

Run: python -m pytest tests/one-offs/test_tools_channel.py -v
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks" / "scripts"))
_mod = importlib.import_module("log-command")

_default_channels = _mod._default_channels
_default_category_routes = _mod._default_category_routes
ChannelConfig = _mod.ChannelConfig
Config = _mod.Config


class TestToolsChannelDefaults:
    """The new `tools` channel exists in defaults with correct file prefix."""

    def test_tools_channel_in_defaults(self):
        channels = _default_channels()
        assert "tools" in channels
        assert channels["tools"].file_prefix == ".tools_"
        assert channels["tools"].enabled is True

    def test_all_default_channels_present(self):
        # Updated for v0.3.5+ (#33-#35): adds `convo` channel
        channels = _default_channels()
        assert set(channels.keys()) == {"shell", "sesslog", "tasks", "unknowns", "tools", "convo"}

    def test_tools_channel_uses_consistent_prefix_pattern(self):
        # All channels follow the .{name}_ pattern
        channels = _default_channels()
        for name, channel in channels.items():
            assert channel.file_prefix.startswith(".")
            assert channel.file_prefix.endswith("_")


class TestToolsRouting:
    """Default category routes include `tools` for most categories."""

    def test_default_route_includes_tools(self):
        routes = _default_category_routes()
        assert "tools" in routes["_default"]
        assert routes["_default"] == ["shell", "sesslog", "tools"]

    def test_task_route_includes_tools(self):
        routes = _default_category_routes()
        assert "tools" in routes["task"]
        assert routes["task"] == ["shell", "sesslog", "tools", "tasks"]

    def test_unknown_route_does_NOT_include_tools(self):
        # Critical: unknown stays focused on discovery, doesn't pollute tools
        routes = _default_category_routes()
        assert "tools" not in routes["unknown"]
        assert routes["unknown"] == ["sesslog", "unknowns"]

    def test_unknown_route_does_NOT_include_shell(self):
        # Regression check from v0.2.1
        routes = _default_category_routes()
        assert "shell" not in routes["unknown"]


class TestConfigMergeBehavior:
    """Customized configs that lack the `tools` channel/route auto-pick up defaults."""

    def test_fresh_config_has_tools_channel(self):
        config = Config()
        assert "tools" in config.routing.channels
        assert config.routing.channels["tools"].enabled is True

    def test_fresh_config_has_tools_in_default_route(self):
        config = Config()
        assert "tools" in config.routing.category_routes["_default"]

    def test_fresh_config_has_tools_in_task_route(self):
        config = Config()
        assert "tools" in config.routing.category_routes["task"]

    def test_per_key_merge_preserves_user_channel_overrides(self):
        # Simulate: user has custom channel + missing `tools` channel.
        # The Config defaults factory creates the base dict; user overlay
        # should leave defaults intact (per-key merge, not full replace).
        config = Config()
        # Simulate user adding a custom channel (existing per-key merge pattern)
        config.routing.channels["my_custom"] = ChannelConfig(file_prefix=".custom_")
        # tools channel must still be present after the user-added one
        assert "tools" in config.routing.channels
        assert "my_custom" in config.routing.channels

    def test_per_key_merge_preserves_user_route_overrides(self):
        # Simulate: user overrides one route, leaves others alone
        config = Config()
        config.routing.category_routes["bash"] = ["shell"]  # user-specific
        # The default `tools` in `_default` route must still apply
        assert "tools" in config.routing.category_routes["_default"]
        # User's bash override took effect
        assert config.routing.category_routes["bash"] == ["shell"]


class TestRoutingResolution:
    """End-to-end: routing resolution sends a tool to all expected channels."""

    def test_bash_tool_routes_to_shell_sesslog_tools(self):
        # Bash category falls through to _default route
        routes = _default_category_routes()
        bash_route = routes.get("bash", routes["_default"])
        assert "shell" in bash_route
        assert "sesslog" in bash_route
        assert "tools" in bash_route

    def test_task_tool_routes_to_all_four_channels(self):
        # task category routes explicitly to shell + sesslog + tools + tasks
        routes = _default_category_routes()
        assert routes["task"] == ["shell", "sesslog", "tools", "tasks"]

    def test_unknown_tool_does_not_reach_tools(self):
        # Unknown tools stay out of the tools investigation view
        routes = _default_category_routes()
        unknown_route = routes["unknown"]
        assert "tools" not in unknown_route
        # Should reach sesslog (kitchen sink) and unknowns (discovery)
        assert "sesslog" in unknown_route
        assert "unknowns" in unknown_route
