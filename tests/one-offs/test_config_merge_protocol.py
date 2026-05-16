"""v0.3.7 #45 fix tests: per-key merge via apply_override protocol.

These tests pin the contract of the apply_override classmethods on
Config / RoutingConfig / ChannelConfig / ChannelOptions / PerformanceConfig.
Together they replace the v0.3.6 whole-record reconstruction in
ConfigLoader._apply_new_config that silently dropped shipped channel
defaults whenever a user provided any partial override.

The two manifestations of Bug #45 the protocol fixes:
  1. Original — user override of an existing channel without `file_prefix`
     was silently skipped entirely.
  2. Extended — user override of an existing channel WITH `file_prefix`
     replaced the whole ChannelConfig (including ChannelOptions defaults
     like fileio's `verbosity="full"` + `newline_policy=RENDER`).

Both stem from the same architectural choice (whole-record replacement
instead of per-key merge). The tests here verify the unified fix.

Run: python -m pytest tests/one-offs/test_config_merge_protocol.py -v
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

# sys.path setup happens in conftest.py
_mod = importlib.import_module("cclogger")
ConfigLoader = _mod.ConfigLoader

from cclogger.config_merge import (
    apply_override_channel_config,
    apply_override_channel_options,
    apply_override_config,
    apply_override_performance_config,
    apply_override_routing_config,
)
from cclogger.models import (
    ChannelConfig,
    ChannelOptions,
    Config,
    NewlinePolicy,
    PerformanceConfig,
    RoutingConfig,
)


# ============================================================================
# Section 1: ChannelOptions.apply_override — per-field merge contract
# ============================================================================


class TestChannelOptionsApplyOverride:
    """ChannelOptions per-field merge: absent keys preserve, present keys override."""

    def test_absent_field_preserves_current_value(self):
        target = ChannelOptions(verbosity="full", formatter="default", suppress_markers=True)
        apply_override_channel_options(target, {"verbosity": "preview"})
        # verbosity overridden, others preserved
        assert target.verbosity == "preview"
        assert target.formatter == "default"
        assert target.suppress_markers is True

    def test_overrides_only_named_fields(self):
        """Setting verbosity does not reset formatter, newline_policy, or any other field."""
        target = ChannelOptions(
            verbosity="full",
            formatter="chat",
            newline_policy=NewlinePolicy.RENDER,
            role_labels={"edit": "EDT"},
            suppress_markers=True,
        )
        apply_override_channel_options(target, {"verbosity": {"max_chars": 50}})
        assert target.verbosity == {"max_chars": 50}
        assert target.formatter == "chat"
        assert target.newline_policy == NewlinePolicy.RENDER
        assert target.role_labels == {"edit": "EDT"}
        assert target.suppress_markers is True

    def test_explicit_none_clears_optional_fields(self):
        target = ChannelOptions(verbosity="full", role_labels={"edit": "EDT"})
        apply_override_channel_options(target, {"verbosity": None, "role_labels": None})
        assert target.verbosity is None
        assert target.role_labels is None

    def test_formatter_override(self):
        target = ChannelOptions(formatter="default")
        apply_override_channel_options(target, {"formatter": "chat"})
        assert target.formatter == "chat"

    def test_formatter_non_string_ignored(self):
        target = ChannelOptions(formatter="chat")
        apply_override_channel_options(target, {"formatter": 42})
        assert target.formatter == "chat"  # non-str silently ignored

    def test_newline_policy_string_override(self):
        target = ChannelOptions()
        apply_override_channel_options(target, {"newline_policy": "render"})
        assert target.newline_policy == "render"  # stored verbatim, coerced at format time

    def test_suppress_markers_override(self):
        target = ChannelOptions(suppress_markers=False)
        apply_override_channel_options(target, {"suppress_markers": True})
        assert target.suppress_markers is True

    def test_role_labels_dict_override(self):
        target = ChannelOptions()
        apply_override_channel_options(target, {"role_labels": {"edit": "EDT", "write": "WRT"}})
        assert target.role_labels == {"edit": "EDT", "write": "WRT"}

    def test_verbosity_dict_validated_for_hint_role_collision(self):
        """Mixed hint+role keys still get the hint keys dropped (validation preserved)."""
        target = ChannelOptions()
        apply_override_channel_options(
            target,
            {"verbosity": {"max_chars": 50, "user": "full"}},
            channel_name="test",
        )
        # max_chars was hint, user was role; mixing → drop hint
        assert target.verbosity == {"user": "full"}

    def test_empty_override_is_noop(self):
        target = ChannelOptions(verbosity="full", formatter="chat")
        apply_override_channel_options(target, {})
        assert target.verbosity == "full"
        assert target.formatter == "chat"

    def test_non_dict_override_is_noop(self):
        target = ChannelOptions(verbosity="full")
        apply_override_channel_options(target, "not a dict")
        apply_override_channel_options(target, None)
        apply_override_channel_options(target, 42)
        assert target.verbosity == "full"


# ============================================================================
# Section 2: ChannelConfig.apply_override — recurses into options
# ============================================================================


class TestChannelConfigApplyOverride:
    """ChannelConfig per-field merge with recursion into options."""

    def test_partial_override_preserves_options(self):
        """Bug #45 manifestation 2: enabling a channel must not reset its options."""
        target = ChannelConfig(
            file_prefix=".fileio_",
            enabled=False,
            options=ChannelOptions(verbosity="full", newline_policy=NewlinePolicy.RENDER),
        )
        apply_override_channel_config(target, {"enabled": True}, "fileio")
        assert target.enabled is True
        assert target.file_prefix == ".fileio_"
        # The whole point of the fix:
        assert target.options.verbosity == "full"
        assert target.options.newline_policy == NewlinePolicy.RENDER

    def test_options_override_is_partial(self):
        """Override of one options field preserves the other options fields."""
        target = ChannelConfig(
            file_prefix=".fileio_",
            options=ChannelOptions(verbosity="full", newline_policy=NewlinePolicy.RENDER),
        )
        apply_override_channel_config(
            target,
            {"options": {"verbosity": {"max_chars": 200}}},
            "fileio",
        )
        assert target.options.verbosity == {"max_chars": 200}
        # newline_policy preserved
        assert target.options.newline_policy == NewlinePolicy.RENDER

    def test_file_prefix_override(self):
        target = ChannelConfig(file_prefix=".old_")
        apply_override_channel_config(target, {"file_prefix": ".new_"})
        assert target.file_prefix == ".new_"

    def test_options_explicit_none_resets_to_defaults(self):
        target = ChannelConfig(
            file_prefix=".fileio_",
            options=ChannelOptions(verbosity="full", newline_policy=NewlinePolicy.RENDER),
        )
        apply_override_channel_config(target, {"options": None}, "fileio")
        assert target.options.verbosity is None
        assert target.options.newline_policy is None
        assert target.options.formatter == "default"

    def test_enabled_coercion(self):
        target = ChannelConfig(file_prefix=".x_", enabled=True)
        apply_override_channel_config(target, {"enabled": "false"})
        assert target.enabled is False
        apply_override_channel_config(target, {"enabled": "true"})
        assert target.enabled is True


# ============================================================================
# Section 3: RoutingConfig.apply_override — channels existing-vs-new dispatch
# ============================================================================


class TestRoutingConfigApplyOverride:
    """RoutingConfig.apply_override merges existing channels per-key,
    requires file_prefix for new channels."""

    def test_existing_channel_partial_override_preserves_shipped_options(self):
        """Bug #45 regression: enabling fileio with no other options must
        keep the shipped verbosity='full' + newline_policy=RENDER."""
        target = RoutingConfig()
        # Sanity: shipped fileio defaults
        assert target.channels["fileio"].enabled is False
        assert target.channels["fileio"].options.verbosity == "full"
        assert target.channels["fileio"].options.newline_policy == NewlinePolicy.RENDER

        # Apply minimal user override (the case that was breaking)
        apply_override_routing_config(target, {"channels": {"fileio": {"enabled": True}}})

        # Enabled flipped, but shipped options PRESERVED
        assert target.channels["fileio"].enabled is True
        assert target.channels["fileio"].options.verbosity == "full"
        assert target.channels["fileio"].options.newline_policy == NewlinePolicy.RENDER

    def test_existing_channel_override_without_file_prefix_succeeds(self):
        """Bug #45 manifestation 1 fix: file_prefix not required for existing channel."""
        target = RoutingConfig()
        # convo channel exists in defaults
        assert "convo" in target.channels
        apply_override_routing_config(
            target,
            {"channels": {"convo": {"options": {"suppress_markers": True}}}},
        )
        assert target.channels["convo"].options.suppress_markers is True
        # file_prefix preserved from defaults
        assert target.channels["convo"].file_prefix == ".convo_"

    def test_new_channel_requires_file_prefix(self):
        target = RoutingConfig()
        # Missing file_prefix: should be skipped silently
        apply_override_routing_config(
            target,
            {"channels": {"my_new_channel": {"enabled": True}}},
        )
        assert "my_new_channel" not in target.channels

    def test_new_channel_with_file_prefix_added(self):
        target = RoutingConfig()
        apply_override_routing_config(
            target,
            {"channels": {"mcp_log": {"file_prefix": ".mcp_", "enabled": True}}},
        )
        assert "mcp_log" in target.channels
        assert target.channels["mcp_log"].file_prefix == ".mcp_"
        assert target.channels["mcp_log"].enabled is True

    def test_new_channel_with_options(self):
        target = RoutingConfig()
        apply_override_routing_config(
            target,
            {
                "channels": {
                    "mcp_log": {
                        "file_prefix": ".mcp_",
                        "options": {"verbosity": "full"},
                    }
                }
            },
        )
        assert target.channels["mcp_log"].options.verbosity == "full"

    def test_existing_channel_options_partial_preserves_other_options(self):
        """Override convo.options.suppress_markers; verbosity/newline_policy preserved."""
        target = RoutingConfig()
        # Shipped convo defaults
        assert target.channels["convo"].options.verbosity == "full"
        assert target.channels["convo"].options.newline_policy == NewlinePolicy.RENDER
        assert target.channels["convo"].options.formatter == "chat"

        apply_override_routing_config(
            target,
            {"channels": {"convo": {"options": {"suppress_markers": True}}}},
        )
        assert target.channels["convo"].options.suppress_markers is True
        assert target.channels["convo"].options.verbosity == "full"
        assert target.channels["convo"].options.newline_policy == NewlinePolicy.RENDER
        assert target.channels["convo"].options.formatter == "chat"

    def test_category_routes_per_key_replace(self):
        target = RoutingConfig()
        # Sanity: shipped meta route
        assert target.category_routes["meta"] == ["sesslog", "agents"]
        apply_override_routing_config(
            target,
            {"category_routes": {"meta": ["sesslog"]}},
        )
        assert target.category_routes["meta"] == ["sesslog"]
        # Other categories preserved
        assert target.category_routes["task"] == ["shell", "sesslog", "tools", "tasks"]

    def test_legacy_subtype_routing_key_silently_ignored(self):
        """v0.3.7-pre (supersedes #48): subtype splitting moved from
        category-keyed routing.subtype_routing to per-channel
        ChannelOptions.subtype_split. Legacy user configs that still set
        the old key must NOT raise; the key is dropped at merge time."""
        target = RoutingConfig()
        # Should not raise even though field no longer exists on dataclass
        apply_override_routing_config(
            target,
            {"subtype_routing": {"bash": True, "meta": ["senior-engineer", "help"]}},
        )
        # No field for it to land on
        assert not hasattr(target, "subtype_routing")

    def test_tool_overrides_per_key_replace(self):
        target = RoutingConfig()
        apply_override_routing_config(
            target,
            {"tool_overrides": {"Grep": ["sesslog"]}},
        )
        assert target.tool_overrides["Grep"] == ["sesslog"]


# ============================================================================
# Section 4: PerformanceConfig.apply_override
# ============================================================================


class TestPerformanceConfigApplyOverride:
    """PerformanceConfig per-field merge with clamping."""

    def test_partial_override_preserves_other_fields(self):
        target = PerformanceConfig(content_preview_length=50, skill_args_length=200)
        apply_override_performance_config(target, {"content_preview_length": 100})
        assert target.content_preview_length == 100
        assert target.skill_args_length == 200  # preserved

    def test_content_preview_length_clamped(self):
        target = PerformanceConfig()
        apply_override_performance_config(target, {"content_preview_length": 5000})
        assert target.content_preview_length == 200  # max
        apply_override_performance_config(target, {"content_preview_length": -10})
        assert target.content_preview_length == 0  # min

    def test_invalid_int_silently_ignored(self):
        target = PerformanceConfig(content_preview_length=42)
        apply_override_performance_config(target, {"content_preview_length": "not a number"})
        assert target.content_preview_length == 42  # unchanged


# ============================================================================
# Section 5: Config.apply_override — top-level dispatch
# ============================================================================


class TestConfigApplyOverride:
    """Config.apply_override walks every nested structure."""

    def test_partial_routing_preserves_unmentioned_routing_fields(self):
        target = Config()
        # Apply only a channels override
        apply_override_config(
            target,
            {"routing": {"channels": {"convo": {"enabled": False}}}},
        )
        assert target.routing.channels["convo"].enabled is False
        # category_routes preserved
        assert "meta" in target.routing.category_routes
        # tool_overrides empty (default)
        assert target.routing.tool_overrides == {}

    def test_combined_override_subtype_split_and_channel_options(self):
        """Realistic v0.3.7-pre sweep: per-channel subtype_split + options merge."""
        target = Config()
        apply_override_config(
            target,
            {
                "routing": {
                    "channels": {
                        "convo": {"options": {"suppress_markers": True}},
                        "tools": {
                            "options": {
                                "verbosity": {"max_chars": 50},
                                "subtype_split": True,
                            }
                        },
                    },
                }
            },
        )
        assert target.routing.channels["convo"].options.suppress_markers is True
        assert target.routing.channels["tools"].options.verbosity == {"max_chars": 50}
        assert target.routing.channels["tools"].options.subtype_split is True
        # Convo's other shipped options preserved (per-key merge)
        assert target.routing.channels["convo"].options.formatter == "chat"
        assert target.routing.channels["convo"].options.newline_policy == NewlinePolicy.RENDER
        # agents shipped default subtype_split=True preserved by per-key merge
        assert target.routing.channels["agents"].options.subtype_split is True

    def test_idempotent(self):
        """Applying the same override twice yields the same result."""
        target1 = Config()
        target2 = Config()
        override = {"routing": {"channels": {"fileio": {"enabled": True}}}}
        apply_override_config(target1, override)
        apply_override_config(target2, override)
        apply_override_config(target2, override)  # second time
        assert target1.routing.channels["fileio"].enabled == target2.routing.channels["fileio"].enabled
        assert target1.routing.channels["fileio"].options.verbosity == target2.routing.channels["fileio"].options.verbosity

    def test_action_only_per_key(self):
        target = Config()
        apply_override_config(
            target,
            {"action_only": {"categories": {"bash": True, "io": True}}},
        )
        assert target.action_only["bash"] is True
        assert target.action_only["io"] is True
        # Other categories preserved
        assert target.action_only["todo"] is True  # default

    def test_failure_capture_per_field(self):
        target = Config()
        apply_override_config(
            target,
            {"failure_capture": {"enabled": True, "max_stderr_lines": 100}},
        )
        assert target.failure_capture_enabled is True
        assert target.failure_capture_max_lines == 100
        # capture_stderr preserved (default True)
        assert target.failure_capture_stderr is True


# ============================================================================
# Section 6: End-to-end via ConfigLoader (integration: Bug #45 regression)
# ============================================================================


def _make_per_channel_layout(tmp_path: Path,
                              global_data: dict | None = None,
                              channels: dict | None = None,
                              overrides: dict | None = None) -> Path:
    subdir = tmp_path / "session-logger"
    subdir.mkdir()
    if global_data:
        (subdir / "_global.json").write_text(json.dumps(global_data), encoding="utf-8")
    if channels:
        ch_dir = subdir / "channels"
        ch_dir.mkdir()
        for name, data in channels.items():
            (ch_dir / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    if overrides:
        (subdir / "overrides.json").write_text(json.dumps(overrides), encoding="utf-8")
    return subdir


class TestConfigLoaderIntegration:
    """End-to-end via ConfigLoader: the real pipeline a user hits."""

    def _setup(self, tmp_path, monkeypatch, single_file_data=None, layout_dir=None):
        single_file = tmp_path / "session-logger.json"
        if single_file_data is not None:
            single_file.write_text(json.dumps(single_file_data), encoding="utf-8")
        subdir = layout_dir if layout_dir else tmp_path / "session-logger"
        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", single_file)
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

    def test_bug_45_manifestation_1_fixed_via_single_file(self, tmp_path, monkeypatch):
        """User enables convo's suppress_markers without re-declaring file_prefix."""
        self._setup(
            tmp_path,
            monkeypatch,
            single_file_data={
                "routing": {
                    "channels": {
                        "convo": {"options": {"suppress_markers": True}}
                    }
                }
            },
        )
        config = ConfigLoader.load()
        # The fix: override applied without file_prefix
        assert config.routing.channels["convo"].options.suppress_markers is True
        # File prefix preserved from shipped defaults
        assert config.routing.channels["convo"].file_prefix == ".convo_"
        # Other shipped options preserved
        assert config.routing.channels["convo"].options.formatter == "chat"

    def test_bug_45_manifestation_2_fixed_via_single_file(self, tmp_path, monkeypatch):
        """User enables fileio with file_prefix workaround; shipped options PRESERVED."""
        self._setup(
            tmp_path,
            monkeypatch,
            single_file_data={
                "routing": {
                    "channels": {
                        "fileio": {"file_prefix": ".fileio_", "enabled": True}
                    }
                }
            },
        )
        config = ConfigLoader.load()
        assert config.routing.channels["fileio"].enabled is True
        # The extended-scope fix: shipped options PRESERVED even with file_prefix workaround
        assert config.routing.channels["fileio"].options.verbosity == "full"
        assert config.routing.channels["fileio"].options.newline_policy == NewlinePolicy.RENDER

    def test_bug_45_per_channel_layout_partial_override(self, tmp_path, monkeypatch):
        """Per-channel directory layout: convo.json with only an enabled field."""
        layout = _make_per_channel_layout(
            tmp_path,
            channels={"convo": {"enabled": False}},
        )
        self._setup(tmp_path, monkeypatch, layout_dir=layout)
        config = ConfigLoader.load()
        # convo disabled
        assert config.routing.channels["convo"].enabled is False
        # File prefix and shipped options preserved
        assert config.routing.channels["convo"].file_prefix == ".convo_"
        assert config.routing.channels["convo"].options.formatter == "chat"
        assert config.routing.channels["convo"].options.newline_policy == NewlinePolicy.RENDER

    def test_new_channel_via_single_file_requires_file_prefix(self, tmp_path, monkeypatch):
        """Declaring a brand-new channel without file_prefix is rejected."""
        self._setup(
            tmp_path,
            monkeypatch,
            single_file_data={
                "routing": {
                    "channels": {
                        "my_brand_new_channel": {"enabled": True}
                    }
                }
            },
        )
        config = ConfigLoader.load()
        assert "my_brand_new_channel" not in config.routing.channels

    def test_new_channel_via_single_file_with_file_prefix_succeeds(self, tmp_path, monkeypatch):
        """Declaring a brand-new channel with file_prefix succeeds."""
        self._setup(
            tmp_path,
            monkeypatch,
            single_file_data={
                "routing": {
                    "channels": {
                        "mcp_log": {
                            "file_prefix": ".mcp_",
                            "enabled": True,
                            "options": {"verbosity": "full"},
                        }
                    },
                    "category_routes": {"mcp": ["sesslog", "mcp_log"]},
                }
            },
        )
        config = ConfigLoader.load()
        assert "mcp_log" in config.routing.channels
        assert config.routing.channels["mcp_log"].options.verbosity == "full"
        assert config.routing.category_routes["mcp"] == ["sesslog", "mcp_log"]


# ============================================================================
# Section 7: End-to-end pipeline checks for documented contracts
# ============================================================================
#
# These pin behavior across the apply_override → formatter resolve boundary.
# The merge protocol stores user values verbatim (e.g., newline_policy as a
# string); the formatter layer is responsible for coercion. These tests pin
# that contract so a regression in either layer is caught.


class TestNewlinePolicyStringEndToEnd:
    """User-config string newline_policy round-trips to NewlinePolicy enum at format time."""

    def test_user_string_render_coerces_to_enum_via_resolve(self):
        """{"newline_policy": "render"} stored as string; _resolve_newline_policy
        returns NewlinePolicy.RENDER. Senior-engineer review finding #1 regression."""
        from cclogger.formatters.legacy import _resolve_newline_policy

        target = ChannelOptions()
        apply_override_channel_options(target, {"newline_policy": "render"})
        # Apply_override stores the string verbatim (documented contract)
        assert target.newline_policy == "render"
        # Resolver coerces to enum at format time
        resolved = _resolve_newline_policy(target, role="user", tool_name=None)
        assert resolved == NewlinePolicy.RENDER

    def test_user_string_escape_coerces_to_enum(self):
        from cclogger.formatters.legacy import _resolve_newline_policy

        target = ChannelOptions()
        apply_override_channel_options(target, {"newline_policy": "escape"})
        resolved = _resolve_newline_policy(target, role="user", tool_name=None)
        assert resolved == NewlinePolicy.ESCAPE

    def test_shipped_enum_default_resolves_without_string_round_trip(self):
        """Shipped fileio default uses NewlinePolicy.RENDER directly (enum, not string)."""
        from cclogger.formatters.legacy import _resolve_newline_policy

        target = ChannelOptions(newline_policy=NewlinePolicy.RENDER)
        resolved = _resolve_newline_policy(target, role="edit", tool_name="Edit")
        assert resolved == NewlinePolicy.RENDER

    def test_user_string_survives_partial_options_merge(self):
        """When user overrides only newline_policy on convo, other options preserved
        AND the string-form newline_policy still resolves correctly."""
        from cclogger.formatters.legacy import _resolve_newline_policy

        # Simulate shipped convo defaults + user override of just newline_policy
        target = ChannelOptions(
            verbosity="full",
            formatter="chat",
            newline_policy=NewlinePolicy.RENDER,
        )
        apply_override_channel_options(target, {"newline_policy": "escape"})
        # User override stored as string; other shipped options preserved
        assert target.newline_policy == "escape"
        assert target.verbosity == "full"
        assert target.formatter == "chat"
        # Resolver coerces the user string back to enum
        resolved = _resolve_newline_policy(target, role="user", tool_name=None)
        assert resolved == NewlinePolicy.ESCAPE


# ============================================================================
# Section 8: File_prefix rename of existing channel
# ============================================================================


class TestFilePrefixRename:
    """Pin the rename-by-override semantic: existing-channel + file_prefix in
    override mutates target.file_prefix in place. Senior-engineer review #3."""

    def test_existing_channel_file_prefix_rename(self):
        target = RoutingConfig()
        # Sanity: shipped convo defaults
        assert target.channels["convo"].file_prefix == ".convo_"
        # User renames the file_prefix on an existing channel
        apply_override_routing_config(
            target,
            {"channels": {"convo": {"file_prefix": ".conversation_"}}},
        )
        # File prefix renamed
        assert target.channels["convo"].file_prefix == ".conversation_"
        # Shipped options preserved (channel still merge-style, not whole-replace)
        assert target.channels["convo"].options.formatter == "chat"
        assert target.channels["convo"].options.newline_policy == NewlinePolicy.RENDER

    def test_file_prefix_rename_does_not_create_duplicate_channel(self):
        """Renaming a shipped channel mutates in place — no new entry added."""
        target = RoutingConfig()
        channel_count_before = len(target.channels)
        apply_override_routing_config(
            target,
            {"channels": {"shell": {"file_prefix": ".sh_"}}},
        )
        assert len(target.channels) == channel_count_before
        assert target.channels["shell"].file_prefix == ".sh_"
