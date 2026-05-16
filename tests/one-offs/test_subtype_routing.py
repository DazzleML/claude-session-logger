"""Tests: subtype splitting framework (v0.3.3 #31; v0.3.7-pre supersedes #48).

Validates per-channel subtype splits like `.shell-bash_*.log`,
`.agents-help_*.log`, `.mcp-github_*.log`.

v0.3.7-pre architecture:
  - Subtype splitting is per-channel via `ChannelOptions.subtype_split`
  - Default: False for every channel EXCEPT `agents` (which ships with True)
  - Field accepts bool (True = split for any subtype) or list[str]
    (only split when extracted subtype is in the list)
  - Legacy `routing.subtype_routing.<category>` key from v0.3.3 #31 is
    REMOVED; any such key in user config is silently ignored at merge
    time (field doesn't exist on RoutingConfig anymore)
  - Single-level only: `.agents-help_*` never chains to `.agents-help-bash_*`

Run: python -m pytest tests/one-offs/test_subtype_routing.py -v
"""

import importlib
from pathlib import Path

# sys.path setup happens in conftest.py
_mod = importlib.import_module("cclogger")

get_subtype = _mod.get_subtype
SUBTYPE_EXTRACTORS = _mod.SUBTYPE_EXTRACTORS
RoutingConfig = _mod.RoutingConfig
Config = _mod.Config
ChannelOptions = _mod.ChannelOptions


class TestSubtypeExtractors:
    """Each category's extractor returns the expected subtype string."""

    def test_bash_extractor_lowercases_tool_name(self):
        assert get_subtype("bash", "Bash", {}) == "bash"
        assert get_subtype("bash", "PowerShell", {}) == "powershell"

    def test_mcp_extractor_returns_server_name(self):
        # mcp__servername__toolname format
        assert get_subtype("mcp", "mcp__github__create_issue", {}) == "github"
        assert get_subtype("mcp", "mcp__zen__chat", {}) == "zen"

    def test_mcp_extractor_returns_none_for_non_mcp_name(self):
        assert get_subtype("mcp", "NotMCP", {}) is None

    def test_meta_extractor_uses_subagent_type(self):
        raw = {"tool_input": {"subagent_type": "senior-engineer"}}
        assert get_subtype("meta", "Task", raw) == "senior-engineer"

    def test_meta_extractor_returns_none_when_subagent_type_missing(self):
        raw = {"tool_input": {"prompt": "do thing"}}
        assert get_subtype("meta", "Task", raw) is None

    def test_skill_extractor_uses_skill_field(self):
        raw = {"tool_input": {"skill": "investigate"}}
        assert get_subtype("skill", "Skill", raw) == "investigate"

    def test_no_extractor_for_unmapped_category(self):
        # `system`, `io`, etc. don't have subtype extractors registered
        assert get_subtype("system", "Read", {"tool_input": {"file_path": "/x"}}) is None
        assert get_subtype("io", "Write", {"tool_input": {"file_path": "/x"}}) is None

    def test_extractor_sanitizes_unsafe_chars(self):
        # Subtype with slash/colon should be sanitized for filesystem
        raw = {"tool_input": {"subagent_type": "weird/name:thing"}}
        result = get_subtype("meta", "Task", raw)
        assert result is not None
        assert "/" not in result
        assert ":" not in result


class TestSubtypeSplitDefaults:
    """Per-channel subtype_split defaults: False for most, True for agents."""

    def test_subtype_split_default_false_for_shell(self):
        config = Config()
        assert config.routing.channels["shell"].options.subtype_split is False

    def test_subtype_split_default_false_for_sesslog_tools_unknowns_convo(self):
        config = Config()
        for name in ("sesslog", "tools", "unknowns", "convo", "tasks", "fileio"):
            assert config.routing.channels[name].options.subtype_split is False, (
                f"channel {name!r} should default subtype_split=False"
            )

    def test_subtype_split_default_true_for_agents(self):
        """Only agents ships with subtype_split=True so `.agents-<subagent>_*`
        materialize without user config (preserves the v0.3.6 user-config
        behavior people relied on for agent debugging)."""
        config = Config()
        assert config.routing.channels["agents"].options.subtype_split is True

    def test_routing_config_has_no_subtype_routing_field(self):
        """Legacy v0.3.3 field is removed. Any user config key is silently
        ignored at merge time (no field to land on)."""
        rc = RoutingConfig()
        assert not hasattr(rc, "subtype_routing")

    def test_legacy_subtype_routing_user_config_silently_ignored(self):
        """User config with the legacy `routing.subtype_routing` key MUST
        not raise; the key is silently dropped by the merge protocol."""
        from cclogger.config_merge import apply_override_routing_config

        rc = RoutingConfig()
        override = {
            "subtype_routing": {"bash": True, "meta": ["help"]},
        }
        # Must not raise
        apply_override_routing_config(rc, override)
        # And no field should have materialized on the dataclass
        assert not hasattr(rc, "subtype_routing")


class TestExpandWithSubtypeChannels:
    """Channel-list expansion based on per-channel subtype_split config."""

    def _make_logger(self):
        SessionContext = _mod.SessionContext
        SessionLogger = _mod.SessionLogger
        config = Config()
        session = SessionContext(
            shell_type="bash",
            session_name="test",
            session_id="test-id-12345",
            username="testuser",
        )
        # SessionLogger init writes session marker; bypass by minimal setup
        logger = SessionLogger.__new__(SessionLogger)
        logger.config = config
        logger.session = session
        return logger

    def test_no_expansion_when_subtype_split_off(self):
        logger = self._make_logger()
        # shell + tools default subtype_split=False
        result = logger._expand_with_subtype_channels(
            ["shell", "tools"], "Bash", "bash",
            raw_json={"tool_name": "Bash", "tool_input": {"command": "ls"}},
        )
        assert result == ["shell", "tools"]

    def test_expansion_only_for_channels_with_subtype_split_true(self):
        """Opt-in PER CHANNEL: enabling subtype_split on `shell` must NOT
        cause `.tools-bash` / `.sesslog-bash` to appear. This is the Bug A
        fix: prior code expanded ALL routed channels when any category
        had the legacy `subtype_routing` flag set."""
        logger = self._make_logger()
        logger.config.routing.channels["shell"].options.subtype_split = True
        # tools + sesslog left at default False
        result = logger._expand_with_subtype_channels(
            ["shell", "tools", "sesslog"], "PowerShell", "bash",
            raw_json={"tool_name": "PowerShell", "tool_input": {"command": "ls"}},
        )
        assert "shell" in result
        assert "shell-powershell" in result, "shell opted in -> expand"
        assert "tools" in result
        assert "tools-powershell" not in result, "tools NOT opted in -> no expand"
        assert "sesslog" in result
        assert "sesslog-powershell" not in result, "sesslog NOT opted in -> no expand"

    def test_subtype_split_list_filters_subtypes(self):
        """list[str] form: only expand for listed subtype names."""
        logger = self._make_logger()
        # Only split shell when subtype is "powershell"
        logger.config.routing.channels["shell"].options.subtype_split = ["powershell"]
        # Bash -> subtype "bash" -> NOT in list -> no expand
        result_bash = logger._expand_with_subtype_channels(
            ["shell"], "Bash", "bash",
            raw_json={"tool_name": "Bash", "tool_input": {"command": "ls"}},
        )
        assert result_bash == ["shell"]
        # PowerShell -> subtype "powershell" -> in list -> expand
        result_ps = logger._expand_with_subtype_channels(
            ["shell"], "PowerShell", "bash",
            raw_json={"tool_name": "PowerShell", "tool_input": {"command": "ls"}},
        )
        assert "shell-powershell" in result_ps

    def test_no_expansion_when_subtype_extracted_is_none(self):
        logger = self._make_logger()
        # agents defaults subtype_split=True
        # Task without subagent_type -> subtype is None -> no expand
        result = logger._expand_with_subtype_channels(
            ["sesslog", "agents"], "Task", "meta",
            raw_json={"tool_name": "Task", "tool_input": {"prompt": "do thing"}},
        )
        assert result == ["sesslog", "agents"]

    def test_agents_default_expansion_works_without_user_config(self):
        """`agents` ships with subtype_split=True so `.agents-<subagent>_*`
        appears with zero user config -- this is the v0.3.7-pre upgrade
        path for users who previously needed `subtype_routing.meta: true`."""
        logger = self._make_logger()
        result = logger._expand_with_subtype_channels(
            ["sesslog", "agents"], "Task", "meta",
            raw_json={"tool_name": "Task", "tool_input": {"subagent_type": "senior-engineer"}},
        )
        assert "sesslog" in result
        assert "agents" in result
        assert "agents-senior-engineer" in result
        # sesslog has subtype_split=False -> no expansion
        assert "sesslog-senior-engineer" not in result

    def test_no_recursion_subtype_does_not_chain(self):
        """Single-level only: `.agents-help_*` MUST never chain to
        `.agents-help-bash_*` even if multiple categories have extractors.
        The expander iterates the ORIGINAL channel list, not the expanded
        one -- subtype-derived channels are not themselves re-expanded."""
        logger = self._make_logger()
        # Even if we somehow asked to expand a subtype-derived name, it
        # shouldn't chain. The original-list iteration enforces this:
        # the loop iterates `channels`, not `expanded`, so newly-appended
        # subtype channels are never re-visited.
        result = logger._expand_with_subtype_channels(
            ["agents"], "Task", "meta",
            raw_json={"tool_name": "Task", "tool_input": {"subagent_type": "help"}},
        )
        # Should contain agents + agents-help, NOT agents-help-anything
        assert result == ["agents", "agents-help"] or result == ["agents", "agents-help"]
        # Verify no chained names sneaked in
        for name in result:
            # Allow at most ONE subtype suffix
            base_part = name.split("-")[0]
            tail = name[len(base_part):]
            # tail is either empty or "-<subtype>" (one segment)
            if tail:
                assert tail.count("-") == 1, (
                    f"chained subtype detected in {name!r} (recursion bug)"
                )


class TestApplyOverrideSubtypeSplit:
    """ChannelOptions.subtype_split merges correctly via the override protocol."""

    def test_bool_true_sets_field(self):
        from cclogger.config_merge import apply_override_channel_options

        opts = ChannelOptions()
        apply_override_channel_options(opts, {"subtype_split": True}, "test")
        assert opts.subtype_split is True

    def test_bool_false_sets_field(self):
        from cclogger.config_merge import apply_override_channel_options

        opts = ChannelOptions(subtype_split=True)
        apply_override_channel_options(opts, {"subtype_split": False}, "test")
        assert opts.subtype_split is False

    def test_list_form_filters_to_strings(self):
        """Non-string entries in the list are silently dropped."""
        from cclogger.config_merge import apply_override_channel_options

        opts = ChannelOptions()
        apply_override_channel_options(
            opts, {"subtype_split": ["help", 42, "explore", None]}, "test"
        )
        assert opts.subtype_split == ["help", "explore"]

    def test_none_resets_to_false(self):
        from cclogger.config_merge import apply_override_channel_options

        opts = ChannelOptions(subtype_split=True)
        apply_override_channel_options(opts, {"subtype_split": None}, "test")
        assert opts.subtype_split is False

    def test_absent_key_preserves_value(self):
        """Per-key merge contract: keys absent from override preserve current."""
        from cclogger.config_merge import apply_override_channel_options

        opts = ChannelOptions(subtype_split=["help", "explore"])
        apply_override_channel_options(
            opts, {"verbosity": "full"}, "test"
        )
        # subtype_split unchanged
        assert opts.subtype_split == ["help", "explore"]


class TestChannelPathDerivation:
    """Subtype channel paths derive correctly from base channel file_prefix."""

    def _make_logger(self):
        SessionContext = _mod.SessionContext
        SessionLogger = _mod.SessionLogger
        config = Config()
        session = SessionContext(
            shell_type="bash",
            session_name="test",
            session_id="test-id-12345",
            username="testuser",
        )
        logger = SessionLogger.__new__(SessionLogger)
        logger.config = config
        logger.session = session
        logger.session_dir = Path("/tmp/sessions")  # mock; not actually used for filesystem
        return logger

    def test_unknown_subtype_base_raises(self):
        # `bash` is a CATEGORY, not a channel; no channel called `bash` is
        # declared in defaults. So `bash-powershell` should raise.
        logger = self._make_logger()
        import pytest
        with pytest.raises(ValueError, match="Unknown channel"):
            logger._get_channel_path("bash-powershell")

    def test_subtype_channel_for_tools(self):
        logger = self._make_logger()
        # tools is a declared channel with prefix .tools_
        path = logger._get_channel_path("tools-powershell")
        # Should derive .tools-powershell_<context>.log
        assert path.name.startswith(".tools-powershell_")
        assert path.name.endswith(".log")

    def test_subtype_channel_for_shell(self):
        logger = self._make_logger()
        path = logger._get_channel_path("shell-powershell")
        assert path.name.startswith(".shell-powershell_")
        assert path.name.endswith(".log")
