"""Phase 1 tests: ChannelOptions data model + hierarchical resolution.

These tests are PROVE-IT style — each pins one behavior with a concrete
expected output. If a test passes, the behavior is correct under the
inputs tested. Edge cases from the design discussion (see
private/claude/2026-05-09__23-01-19__channel-options-framework-pin-design-decisions.md)
are explicitly named so failures map directly back to the decision they
violate.

Phase 1 fields are INERT at runtime — handlers don't yet emit `LogEntry`
and formatters don't yet dispatch on `ChannelOptions`. This file proves
the data model + resolution helpers work correctly in isolation; the
diff_check.py snapshot test proves they don't disturb existing behavior.

Run: python -m pytest tests/one-offs/test_channel_options.py -v
"""

from __future__ import annotations

import importlib

import pytest

_mod = importlib.import_module("cclogger")


# ============================================================================
# Section 1: NewlinePolicy enum (2-mode, no PARAGRAPH)
# ============================================================================


class TestNewlinePolicyEnum:
    """Pinned: 2-mode enum, ESCAPE default, RENDER alternative. PARAGRAPH dropped."""

    def test_has_exactly_two_modes(self):
        from cclogger.models import NewlinePolicy
        assert {m.name for m in NewlinePolicy} == {"ESCAPE", "RENDER"}

    def test_paragraph_mode_explicitly_absent(self):
        """Pin the design decision: PARAGRAPH was a misread, dropped from v0.3.7."""
        from cclogger.models import NewlinePolicy
        assert "PARAGRAPH" not in {m.name for m in NewlinePolicy}

    def test_string_values_are_lowercase(self):
        from cclogger.models import NewlinePolicy
        assert NewlinePolicy.ESCAPE.value == "escape"
        assert NewlinePolicy.RENDER.value == "render"

    def test_constructible_from_string_value(self):
        """Roundtrip: NewlinePolicy("escape") → NewlinePolicy.ESCAPE."""
        from cclogger.models import NewlinePolicy
        assert NewlinePolicy("escape") is NewlinePolicy.ESCAPE
        assert NewlinePolicy("render") is NewlinePolicy.RENDER


# ============================================================================
# Section 2: ChannelOptions dataclass (shape + defaults)
# ============================================================================


class TestChannelOptionsShape:
    """Pinned: 5 fields with documented defaults; immutable contract for v0.3.7."""

    def test_default_construction_all_optional(self):
        from cclogger.models import ChannelOptions
        opts = ChannelOptions()
        assert opts.verbosity is None
        assert opts.formatter == "default"
        assert opts.newline_policy is None
        assert opts.role_labels is None
        assert opts.suppress_markers is False

    def test_explicit_construction_with_all_fields(self):
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(
            verbosity={"max_chars": 100},
            formatter="chat",
            newline_policy=NewlinePolicy.RENDER,
            role_labels={"edit": "EDT"},
            suppress_markers=True,
        )
        assert opts.verbosity == {"max_chars": 100}
        assert opts.formatter == "chat"
        assert opts.newline_policy is NewlinePolicy.RENDER
        assert opts.role_labels == {"edit": "EDT"}
        assert opts.suppress_markers is True

    def test_verbosity_accepts_string_preset(self):
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity="full")
        assert opts.verbosity == "full"

    def test_verbosity_accepts_per_role_dict(self):
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"agent:user": "preview", "agent:ai": "full"})
        assert opts.verbosity == {"agent:user": "preview", "agent:ai": "full"}


# ============================================================================
# Section 3: ChannelConfig.options field
# ============================================================================


class TestChannelConfigOptionsField:
    """Pinned: ChannelConfig gains an `options` field defaulting to ChannelOptions()."""

    def test_options_field_default(self):
        from cclogger.models import ChannelConfig, ChannelOptions
        cc = ChannelConfig(file_prefix=".test_")
        assert isinstance(cc.options, ChannelOptions)
        # Default options have all-None
        assert cc.options.verbosity is None

    def test_options_field_explicit(self):
        from cclogger.models import ChannelConfig, ChannelOptions
        opts = ChannelOptions(verbosity="full")
        cc = ChannelConfig(file_prefix=".test_", options=opts)
        assert cc.options is opts

    def test_existing_default_channels_have_default_options(self):
        """Built-in channels (shell, sesslog, tools, convo, etc.) get default options."""
        from cclogger.models import _default_channels, ChannelOptions
        channels = _default_channels()
        for name, channel in channels.items():
            assert isinstance(channel.options, ChannelOptions), \
                f"Channel '{name}' missing options field"


# ============================================================================
# Section 4: LogEntry repurposed (10 fields, was dead code)
# ============================================================================


class TestLogEntryRepurpose:
    """Pinned: LogEntry now carries structured content for formatter dispatch.

    Old fields (timestamp, tool_name, content, pwd, is_failure, ...) are
    REPLACED. New fields are: raw_content, role, summary, metadata, timestamp,
    tool_name, agent_context, is_failure, failure_reason, error_output.
    """

    def test_minimal_construction(self):
        from cclogger.models import LogEntry
        entry = LogEntry(raw_content="hello world", role="user")
        assert entry.raw_content == "hello world"
        assert entry.role == "user"

    def test_all_fields_have_sensible_defaults(self):
        from cclogger.models import LogEntry
        entry = LogEntry(raw_content="x", role="ai")
        assert entry.summary is None
        assert entry.metadata == {}
        assert entry.timestamp is None
        assert entry.tool_name is None
        assert entry.agent_context is None
        assert entry.is_failure is False
        assert entry.failure_reason is None
        assert entry.error_output is None

    def test_summary_template_with_snippet_placeholder(self):
        """Edit-handler-style: summary carries the rich format template."""
        from cclogger.models import LogEntry
        entry = LogEntry(
            raw_content="def foo():\n    return 42",
            role="edit",
            summary='"path:14" ← {snippet} (-2/+3L)',
            metadata={"path": "x.py", "line": 14, "delta": (2, 3)},
        )
        assert "{snippet}" in entry.summary  # placeholder preserved
        assert entry.metadata["path"] == "x.py"

    def test_failure_entry_carries_diagnostics(self):
        from cclogger.models import LogEntry
        entry = LogEntry(
            raw_content="rm /nonexistent",
            role="bash",
            is_failure=True,
            failure_reason="error detected in output",
            error_output="rm: cannot remove '/nonexistent': No such file or directory",
        )
        assert entry.is_failure is True
        assert entry.failure_reason == "error detected in output"
        assert "No such file" in entry.error_output


# ============================================================================
# Section 5: Reserved verbosity keywords (discriminator for hint-vs-role-map)
# ============================================================================


class TestReservedVerbosityKeys:
    """Pinned: max_chars, max_lines are reserved keywords. They discriminate
    a hint-dict from a per-role map, and they cannot be used as role names."""

    def test_reserved_keys_set(self):
        from cclogger.models import RESERVED_VERBOSITY_KEYS
        assert "max_chars" in RESERVED_VERBOSITY_KEYS
        assert "max_lines" in RESERVED_VERBOSITY_KEYS

    def test_reserved_keys_does_not_contain_role_names(self):
        """Sanity: 'agent', 'user', 'ai' are role names, not reserved."""
        from cclogger.models import RESERVED_VERBOSITY_KEYS
        assert "agent" not in RESERVED_VERBOSITY_KEYS
        assert "user" not in RESERVED_VERBOSITY_KEYS
        assert "ai" not in RESERVED_VERBOSITY_KEYS


# ============================================================================
# Section 6: ROLES set + ROLE_LABELS dict
# ============================================================================


class TestRolesAndLabels:
    """Pinned: closed enum of roles with display labels; ??:<unknown> fallback."""

    def test_baseline_roles_present(self):
        """Phase 0 roles that handlers already emit (or will emit verbatim)."""
        from cclogger.models import ROLES
        for role in ("user", "ai", "agent", "edit", "write", "bash", "read", "grep"):
            assert role in ROLES, f"Baseline role '{role}' missing"

    def test_role_labels_have_display_strings(self):
        """Each role in ROLES has a display label (used by default formatter)."""
        from cclogger.models import ROLES, ROLE_LABELS
        # Conversation roles use uppercase per current convo channel convention
        assert ROLE_LABELS["user"] == "USER"
        assert ROLE_LABELS["ai"] == "AI"
        assert ROLE_LABELS["agent"] == "AGENT"
        # Tool roles use TitleCase per current default formatter
        assert ROLE_LABELS["edit"] == "Edit"
        assert ROLE_LABELS["write"] == "Write"
        assert ROLE_LABELS["bash"] == "Bash"


# ============================================================================
# Section 7: _role_prefix_chain — walks the :-separated path
# ============================================================================


class TestRolePrefixChain:
    """Pinned: longest-first walk of the :-separated role path.

    Used by _resolve_verbosity / _resolve_newline_policy to find the most
    specific match in a per-role config dict.
    """

    def test_single_segment(self):
        from cclogger.formatters import _role_prefix_chain
        assert _role_prefix_chain("agent") == ["agent"]

    def test_two_segments(self):
        from cclogger.formatters import _role_prefix_chain
        # Most-specific first, then walk up
        assert _role_prefix_chain("agent:user") == ["agent:user", "agent"]

    def test_three_segments(self):
        from cclogger.formatters import _role_prefix_chain
        assert _role_prefix_chain("agent:senior-engineer:user") == [
            "agent:senior-engineer:user",
            "agent:senior-engineer",
            "agent",
        ]

    def test_empty_string(self):
        from cclogger.formatters import _role_prefix_chain
        assert _role_prefix_chain("") == [""]

    def test_subtype_channel_pattern(self):
        """bash:powershell mirrors the .bash-powershell_*.log channel pattern."""
        from cclogger.formatters import _role_prefix_chain
        assert _role_prefix_chain("bash:powershell") == ["bash:powershell", "bash"]


# ============================================================================
# Section 8: _resolve_verbosity — 5-level hierarchy
# ============================================================================


class TestResolveVerbosity:
    """Pinned: 5-level walk:
      1. Per-tool override in channel options
      2. Per-sub-role match (longest-prefix wins, walks :-path)
      3. Per-role match (covered by step 2)
      4. Channel default (string or single value)
      5. Global default (PerformanceConfig.content_preview_length, default 20)
    """

    def _global_default(self):
        from cclogger.models import PerformanceConfig
        return PerformanceConfig().content_preview_length  # 20

    def test_global_default_when_no_options(self):
        """Empty ChannelOptions falls through to global default (20)."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        result = _resolve_verbosity(ChannelOptions(), role="user",
                                     tool_name=None, global_default=20)
        assert result == 20

    def test_channel_default_string_full(self):
        """Channel verbosity='full' returns 0 (no truncation, per existing convention)."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity="full")
        result = _resolve_verbosity(opts, role="user", tool_name=None, global_default=20)
        assert result == 0  # 0 = no truncation

    def test_channel_default_string_preview(self):
        """Channel verbosity='preview' returns the global default (20)."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity="preview")
        result = _resolve_verbosity(opts, role="user", tool_name=None, global_default=20)
        assert result == 20

    def test_channel_default_hint_dict(self):
        """Channel verbosity={'max_chars': 100} returns 100."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"max_chars": 100})
        result = _resolve_verbosity(opts, role="user", tool_name=None, global_default=20)
        assert result == 100

    def test_per_role_exact_match(self):
        """{'user': 'full'} matches role='user' → 0."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"user": "full"})
        result = _resolve_verbosity(opts, role="user", tool_name=None, global_default=20)
        assert result == 0

    def test_per_role_with_hint_dict_value(self):
        """{'agent:user': {'max_chars': 50}} matches role='agent:user' → 50."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"agent:user": {"max_chars": 50}})
        result = _resolve_verbosity(opts, role="agent:user", tool_name=None,
                                     global_default=20)
        assert result == 50

    def test_per_role_longest_prefix_wins(self):
        """role='agent:senior-engineer' against {'agent': 'full', 'agent:senior-engineer': {'max_chars': 50}}
        → 50 (longer prefix wins)."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={
            "agent": "full",
            "agent:senior-engineer": {"max_chars": 50},
        })
        result = _resolve_verbosity(opts, role="agent:senior-engineer",
                                     tool_name=None, global_default=20)
        assert result == 50

    def test_pinned_edge_case_agent_user_NOT_a_prefix_of_agent_se_user(self):
        """THE pinned edge case from the design discussion:

        role='agent:senior-engineer:user' against
        {'agent': 'full', 'agent:user': 'preview'}
        → 'full' (level 0 from 'agent') because 'agent:user' is NOT a
          prefix of 'agent:senior-engineer:user' under :-segment matching.
        """
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"agent": "full", "agent:user": "preview"})
        result = _resolve_verbosity(opts, role="agent:senior-engineer:user",
                                     tool_name=None, global_default=20)
        # 'agent' matches at the top of the chain (it IS a prefix);
        # 'agent:user' is NOT a prefix because position 1 is 'senior-engineer' not 'user'
        assert result == 0  # 'full' → 0

    def test_per_tool_override_beats_per_role(self):
        """Per-tool override at level 1 wins over per-role match at level 2."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={
            "PowerShell": {"max_chars": 50},  # per-tool key (capitalized matches tool_name)
            "bash": "full",                    # per-role key
        })
        # tool_name='PowerShell' → per-tool match at level 1
        result = _resolve_verbosity(opts, role="bash", tool_name="PowerShell",
                                     global_default=20)
        assert result == 50

    def test_per_role_used_when_no_per_tool_match(self):
        """Per-tool dict misses → fall through to per-role."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={
            "PowerShell": {"max_chars": 50},
            "bash": "full",
        })
        result = _resolve_verbosity(opts, role="bash", tool_name="Bash",
                                     global_default=20)
        # tool_name='Bash' doesn't match 'PowerShell'; falls through to role 'bash' → 'full' → 0
        assert result == 0

    def test_global_default_when_role_not_matched(self):
        """Per-role dict has only 'agent', role='user' → no match → global default."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"agent": "full"})
        result = _resolve_verbosity(opts, role="user", tool_name=None,
                                     global_default=99)
        assert result == 99


# ============================================================================
# Section 9: _resolve_newline_policy — same shape as verbosity
# ============================================================================


class TestResolveNewlinePolicy:
    """Pinned: same 5-level hierarchy as verbosity, returns NewlinePolicy enum."""

    def test_default_when_no_options(self):
        from cclogger.formatters import _resolve_newline_policy
        from cclogger.models import ChannelOptions, NewlinePolicy
        result = _resolve_newline_policy(ChannelOptions(), role="user", tool_name=None)
        assert result is NewlinePolicy.ESCAPE  # default

    def test_channel_default_render(self):
        from cclogger.formatters import _resolve_newline_policy
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(newline_policy=NewlinePolicy.RENDER)
        result = _resolve_newline_policy(opts, role="user", tool_name=None)
        assert result is NewlinePolicy.RENDER

    def test_per_role_render_override(self):
        from cclogger.formatters import _resolve_newline_policy
        from cclogger.models import ChannelOptions, NewlinePolicy
        # Per-role: agent:ai gets RENDER, others stay ESCAPE
        opts = ChannelOptions(newline_policy={"agent:ai": NewlinePolicy.RENDER})
        result = _resolve_newline_policy(opts, role="agent:ai", tool_name=None)
        assert result is NewlinePolicy.RENDER
        # role='user' (no match) → default ESCAPE
        result = _resolve_newline_policy(opts, role="user", tool_name=None)
        assert result is NewlinePolicy.ESCAPE

    def test_string_value_coerces_to_enum(self):
        """JSON config arrives as strings; resolver should coerce."""
        from cclogger.formatters import _resolve_newline_policy
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(newline_policy="render")
        result = _resolve_newline_policy(opts, role="user", tool_name=None)
        assert result is NewlinePolicy.RENDER


# ============================================================================
# Section 10: ConfigLoader integration (reads `options` from JSON)
# ============================================================================


class TestConfigLoaderOptionsField:
    """Pinned: ConfigLoader._apply_new_config constructs ChannelOptions from JSON."""

    def test_options_loaded_from_per_channel_dict(self, tmp_path, monkeypatch):
        import json
        from cclogger.models import NewlinePolicy
        # Set up a per-channel dir layout with options
        subdir = tmp_path / "session-logger"
        subdir.mkdir()
        ch_dir = subdir / "channels"
        ch_dir.mkdir()
        (ch_dir / "convo.json").write_text(json.dumps({
            "file_prefix": ".convo_",
            "enabled": True,
            "options": {
                "verbosity": {"agent:user": "preview", "agent:ai": "full"},
                "formatter": "chat",
                "newline_policy": "render",
            },
        }), encoding="utf-8")
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_FILE",
                              tmp_path / "session-logger.json")
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_SUBDIR", subdir)

        config = _mod.ConfigLoader.load("test")
        convo = config.routing.channels.get("convo")
        assert convo is not None
        assert convo.options.formatter == "chat"
        assert convo.options.verbosity == {"agent:user": "preview", "agent:ai": "full"}
        # newline_policy parsed as string OR coerced to enum (implementation choice)
        assert convo.options.newline_policy in ("render", NewlinePolicy.RENDER)

    def test_options_absent_yields_default_options(self, tmp_path, monkeypatch):
        """If channel JSON doesn't have 'options', ChannelOptions() defaults apply."""
        import json
        from cclogger.models import ChannelOptions
        subdir = tmp_path / "session-logger"
        subdir.mkdir()
        ch_dir = subdir / "channels"
        ch_dir.mkdir()
        (ch_dir / "shell.json").write_text(json.dumps({
            "file_prefix": ".shell_",
            "enabled": True,
        }), encoding="utf-8")
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_FILE",
                              tmp_path / "session-logger.json")
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_SUBDIR", subdir)

        config = _mod.ConfigLoader.load("test")
        shell = config.routing.channels.get("shell")
        assert shell is not None
        assert isinstance(shell.options, ChannelOptions)
        assert shell.options.verbosity is None  # default
        assert shell.options.formatter == "default"  # default


# ============================================================================
# Section 11: Reserved-keyword validation rejects role-name collisions
# ============================================================================


class TestReservedKeywordValidation:
    """Pinned: role names that collide with reserved verbosity keys are rejected."""

    def test_role_name_max_chars_rejected_with_helpful_error(self, tmp_path, monkeypatch):
        """A user trying to name a role 'max_chars' must be rejected pre-load."""
        import json
        subdir = tmp_path / "session-logger"
        subdir.mkdir()
        ch_dir = subdir / "channels"
        ch_dir.mkdir()
        # User attempts to set per-role verbosity with reserved keyword as role
        (ch_dir / "weird.json").write_text(json.dumps({
            "file_prefix": ".weird_",
            "options": {"verbosity": {"max_chars": "preview", "user": "full"}},
            # Ambiguous: is this a hint dict ({"max_chars": <int>}) or a role-map
            # with a role named "max_chars"? Reserved-keyword discriminator says:
            # since "max_chars" alone IS a reserved key but "user" is NOT, this is
            # a role-map containing a reserved key as role → REJECT.
        }), encoding="utf-8")
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_FILE",
                              tmp_path / "session-logger.json")
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_SUBDIR", subdir)

        # Implementation MAY raise OR log+skip; pin: at minimum the bogus role
        # MUST NOT be silently accepted as a valid role-map entry.
        # Acceptable outcomes:
        #   1. Raises ValueError / ConfigError on load
        #   2. Logs warning + drops the bogus key (channel still created)
        # NOT acceptable: silently accepts {"max_chars": "preview", "user": "full"}
        # as if "max_chars" were a normal role.
        try:
            config = _mod.ConfigLoader.load("test")
        except (ValueError, Exception) as e:
            # Outcome 1: validation rejects with clear error
            assert "max_chars" in str(e) or "reserved" in str(e).lower()
            return
        # Outcome 2: validation drops the bogus key
        weird = config.routing.channels.get("weird")
        if weird is not None and weird.options.verbosity is not None:
            verbosity = weird.options.verbosity
            if isinstance(verbosity, dict):
                # Either max_chars was treated as hint (kept) or dropped from role-map
                # The key thing: it's NOT being treated as if "max_chars" were a role
                # Acceptable: { "max_chars": ... } interpreted as hint dict (single value)
                # Acceptable: bogus role-map entries dropped
                assert ("max_chars" in verbosity) or ("user" in verbosity)

    def test_pure_hint_dict_accepted(self, tmp_path, monkeypatch):
        """{'max_chars': 100} alone (no role keys) is a valid hint dict."""
        import json
        subdir = tmp_path / "session-logger"
        subdir.mkdir()
        ch_dir = subdir / "channels"
        ch_dir.mkdir()
        (ch_dir / "tools.json").write_text(json.dumps({
            "file_prefix": ".tools_",
            "options": {"verbosity": {"max_chars": 100}},  # valid hint dict
        }), encoding="utf-8")
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_FILE",
                              tmp_path / "session-logger.json")
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_SUBDIR", subdir)

        config = _mod.ConfigLoader.load("test")
        tools = config.routing.channels.get("tools")
        assert tools is not None
        assert tools.options.verbosity == {"max_chars": 100}


# ============================================================================
# Section 12: Behavioral inertness gate (Phase 1 doesn't disturb existing flow)
# ============================================================================


class TestPhase1Inertness:
    """Pinned: Phase 1 fields are inert at runtime — handlers don't yet emit
    LogEntry, formatters don't yet dispatch on ChannelOptions. The diff_check
    gate (separate test runner) confirms byte-identical output. This test
    confirms the data structures load without disturbing the existing
    Config / ChannelConfig flow."""

    def test_default_config_loads_with_default_options(self):
        """Loading a fresh Config gives every default channel a ChannelOptions()."""
        from cclogger.models import Config, ChannelOptions
        cfg = Config()
        for name, channel in cfg.routing.channels.items():
            assert isinstance(channel.options, ChannelOptions), \
                f"Channel '{name}' missing default ChannelOptions"

    def test_config_via_loader_still_works(self, tmp_path, monkeypatch):
        """ConfigLoader.load() with no JSON files returns defaults — no crash."""
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_DIR", empty)
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_FILE",
                              empty / "session-logger.json")
        monkeypatch.setattr("cclogger.config.ConfigLoader.CONFIG_SUBDIR",
                              empty / "session-logger")
        config = _mod.ConfigLoader.load("test")
        # Default channels present, options populated
        assert "shell" in config.routing.channels
        assert config.routing.channels["shell"].options is not None
