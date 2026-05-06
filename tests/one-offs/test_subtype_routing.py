"""Tests: subtype routing framework (v0.3.3, #31).

Validates per-subtype channel splits like .bash-powershell_*.log,
.mcp-github_*.log, .agents-help_*.log, etc.

Default OFF for all categories -- opt-in via routing.subtype_routing config.

Run: python -m pytest tests/one-offs/test_subtype_routing.py -v
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks" / "scripts"))
_mod = importlib.import_module("log-command")

get_subtype = _mod.get_subtype
SUBTYPE_EXTRACTORS = _mod.SUBTYPE_EXTRACTORS
RoutingConfig = _mod.RoutingConfig
Config = _mod.Config


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


class TestSubtypeRoutingConfigDefaults:
    """Subtype routing is OFF by default for backwards compat."""

    def test_default_subtype_routing_is_empty(self):
        config = RoutingConfig()
        assert config.subtype_routing == {}

    def test_full_config_has_subtype_routing_field(self):
        config = Config()
        assert hasattr(config.routing, "subtype_routing")
        assert config.routing.subtype_routing == {}


class TestExpandWithSubtypeChannels:
    """Channel list expansion based on subtype routing config."""

    def _make_logger(self):
        # Minimal SessionLogger-like object that has the methods we need
        # We can't easily instantiate the real one, so we test the static
        # logic via a manual config + the standalone helpers
        from datetime import datetime
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

    def test_no_expansion_when_subtype_routing_off(self):
        logger = self._make_logger()
        # subtype_routing default = {} (off for all)
        result = logger._expand_with_subtype_channels(
            ["shell", "tools"], "Bash", "bash",
            raw_json={"tool_name": "Bash", "tool_input": {"command": "ls"}},
        )
        assert result == ["shell", "tools"]

    def test_expansion_when_subtype_routing_true(self):
        logger = self._make_logger()
        logger.config.routing.subtype_routing["bash"] = True
        result = logger._expand_with_subtype_channels(
            ["shell", "tools"], "PowerShell", "bash",
            raw_json={"tool_name": "PowerShell", "tool_input": {"command": "ls"}},
        )
        # Should add subtype-derived channels
        assert "shell" in result
        assert "tools" in result
        assert "shell-powershell" in result
        assert "tools-powershell" in result

    def test_expansion_only_for_listed_subtypes(self):
        logger = self._make_logger()
        # Only split for "powershell" subtype, not "bash"
        logger.config.routing.subtype_routing["bash"] = ["powershell"]
        # Bash subtype = "bash" -- not in list, so no split
        result_bash = logger._expand_with_subtype_channels(
            ["shell"], "Bash", "bash",
            raw_json={"tool_name": "Bash", "tool_input": {"command": "ls"}},
        )
        assert result_bash == ["shell"]
        # PowerShell subtype = "powershell" -- in list, so split
        result_ps = logger._expand_with_subtype_channels(
            ["shell"], "PowerShell", "bash",
            raw_json={"tool_name": "PowerShell", "tool_input": {"command": "ls"}},
        )
        assert "shell-powershell" in result_ps

    def test_no_expansion_when_subtype_extracted_is_none(self):
        logger = self._make_logger()
        logger.config.routing.subtype_routing["meta"] = True
        # Task without subagent_type -> subtype is None
        result = logger._expand_with_subtype_channels(
            ["sesslog"], "Task", "meta",
            raw_json={"tool_name": "Task", "tool_input": {"prompt": "do thing"}},
        )
        assert result == ["sesslog"]


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
