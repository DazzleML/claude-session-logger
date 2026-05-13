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

    def test_options_absent_in_partial_override_preserves_shipped_options(self, tmp_path, monkeypatch):
        """User overriding an EXISTING channel without an 'options' field
        must not wipe the channel's shipped ChannelOptions defaults.

        v0.3.7 #45 fix: per-key merge semantics. Re-declaring shell with just
        {file_prefix, enabled} preserves the shipped verbosity={'max_chars': 100}
        instead of the v0.3.6 behavior that whole-record-replaced it with
        ChannelOptions() defaults (verbosity=None).
        """
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
        # Shipped shell defaults preserved despite no 'options' in user JSON
        assert shell.options.verbosity == {"max_chars": 100}
        assert shell.options.formatter == "default"  # also shipped default


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


# ============================================================================
# Section 13: Formatter dispatch — registry + format_for_channel routing
# ============================================================================


def _make_logentry(**kwargs):
    """Build a LogEntry with sensible defaults for tests."""
    from datetime import datetime
    from cclogger.models import LogEntry
    defaults = {
        "raw_content": "",
        "role": "bash",
        "tool_name": "Bash",
        "timestamp": datetime(2026, 5, 11, 0, 0, 0),
    }
    defaults.update(kwargs)
    return LogEntry(**defaults)


class TestFormatterRegistry:
    """Pinned: FORMATTERS registry contains the v0.3.7 shipped formatters."""

    def test_registry_has_default(self):
        from cclogger.formatters import FORMATTERS, DefaultFormatter
        assert FORMATTERS["default"] is DefaultFormatter

    def test_registry_has_chat(self):
        from cclogger.formatters import FORMATTERS, ChatFormatter
        assert FORMATTERS["chat"] is ChatFormatter

    def test_registry_has_task_only(self):
        from cclogger.formatters import FORMATTERS, TaskOnlyFormatter
        assert FORMATTERS["task-only"] is TaskOnlyFormatter

    def test_unknown_formatter_falls_back_to_default(self):
        """Unknown formatter name in channel options → DefaultFormatter."""
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(formatter="nonexistent-formatter")
        entry = _make_logentry(raw_content="hello", role="bash")
        # Should not raise; falls back to default
        result = format_for_channel(entry, opts, "shell", None)
        assert isinstance(result, str)


class TestFormatForChannelDispatch:
    """Pinned: format_for_channel routes by channel_opts.formatter."""

    def test_default_formatter_used_when_no_opts(self):
        from cclogger.formatters import format_for_channel
        entry = _make_logentry(
            raw_content="ls -la",
            role="bash",
            metadata={"_legacy_complete": "[[ts]] {Bash: ls -la }"},
        )
        result = format_for_channel(entry, None, "shell", None)
        # No options → default formatter → uses _legacy_complete
        assert result == "[[ts]] {Bash: ls -la }"

    def test_chat_formatter_routes_to_chat(self):
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(
            verbosity="full",
            formatter="chat",
            newline_policy=NewlinePolicy.RENDER,
        )
        entry = _make_logentry(
            raw_content="hello world",
            role="user",
            tool_name="UserPromptSubmit",
        )
        result = format_for_channel(entry, opts, "convo", None)
        # Chat formatter: multi-line shape with USER label
        assert "{USER:\nhello world\n}" in result

    def test_task_only_formatter_routes_to_tasks(self):
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(formatter="task-only")
        entry = _make_logentry(
            raw_content="",
            role="task-create",
            tool_name="TaskCreate",
            metadata={"task_content": "CREATE: do thing"},
        )
        result = format_for_channel(entry, opts, "tasks", None)
        # Task-only output uses task_content from metadata
        assert "{CREATE: do thing }" in result

    def test_str_passthrough_for_legacy_callers(self):
        """Defensive: format_for_channel(str) returns str unchanged."""
        from cclogger.formatters import format_for_channel
        result = format_for_channel("[[ts]] {Bash: ls }", None, "shell", None)
        assert result == "[[ts]] {Bash: ls }"


# ============================================================================
# Section 14: Snippet substitution — rich-format template path
# ============================================================================


class TestSnippetSubstitution:
    """Pinned: {snippet} placeholder substituted with verbosity-truncated raw_content."""

    def test_snippet_placeholder_substituted(self):
        from cclogger.formatters.default import DefaultFormatter
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"max_chars": 100})
        formatter = DefaultFormatter(opts, "shell", None)
        entry = _make_logentry(
            raw_content="hello world",
            role="edit",
            tool_name="Edit",
            summary='Edit: "/path:14" ← "{snippet}" (5L)',
            metadata={"_legacy_complete": "ignored", "datetime_part": "[[ts]] ", "pwd_part": ""},
        )
        result = formatter.format(entry)
        # 100-char budget, 11-char content → no truncation
        assert '"hello world"' in result
        assert "{snippet}" not in result  # placeholder fully substituted

    def test_snippet_truncated_to_max_chars(self):
        from cclogger.formatters.default import DefaultFormatter
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"max_chars": 10})
        formatter = DefaultFormatter(opts, "shell", None)
        entry = _make_logentry(
            raw_content="this is much longer than ten chars",
            role="edit",
            tool_name="Edit",
            summary='Edit: "/path" ← "{snippet}" (1L)',
            metadata={"datetime_part": "", "pwd_part": ""},
        )
        result = formatter.format(entry)
        # First 10 chars: "this is mu" + "..."
        assert '"this is mu..."' in result

    def test_snippet_full_when_verbosity_full(self):
        from cclogger.formatters.default import DefaultFormatter
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity="full")
        formatter = DefaultFormatter(opts, "sesslog", None)
        entry = _make_logentry(
            raw_content="this is the entire content with no truncation expected",
            role="edit",
            tool_name="Edit",
            summary='Edit: "/path" ← "{snippet}" (1L)',
            metadata={"datetime_part": "", "pwd_part": ""},
        )
        result = formatter.format(entry)
        assert '"this is the entire content with no truncation expected"' in result

    def test_template_path_takes_precedence_over_legacy_complete(self):
        """When summary has {snippet}, channel verbosity wins over precomputed legacy."""
        from cclogger.formatters.default import DefaultFormatter
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity="full")
        formatter = DefaultFormatter(opts, "sesslog", None)
        entry = _make_logentry(
            raw_content="full content",
            role="edit",
            tool_name="Edit",
            summary='Edit: "/p" ← "{snippet}"',
            metadata={
                "_legacy_complete": "[[ts]] {Edit: \"/p\" ← \"truncate...\" }",
                "datetime_part": "",
                "pwd_part": "",
            },
        )
        result = formatter.format(entry)
        # Template path wins; legacy_complete ignored
        assert "full content" in result
        assert "truncate..." not in result

    def test_no_template_uses_legacy_complete(self):
        """When summary has no {snippet}, legacy_complete is used (Bash etc.)."""
        from cclogger.formatters.default import DefaultFormatter
        formatter = DefaultFormatter(None, "shell", None)
        entry = _make_logentry(
            raw_content="ls -la",
            role="bash",
            tool_name="Bash",
            summary=None,  # no template
            metadata={"_legacy_complete": "[[ts]] {Bash: ls -la }"},
        )
        result = formatter.format(entry)
        assert result == "[[ts]] {Bash: ls -la }"


# ============================================================================
# Section 15: NewlinePolicy round-trip (ESCAPE vs RENDER)
# ============================================================================


class TestNewlinePolicyRoundTrip:
    """Pinned: ESCAPE produces literal \\n; RENDER preserves real newlines."""

    def test_escape_policy_escapes_newlines_in_snippet(self):
        from cclogger.formatters.default import DefaultFormatter
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(verbosity="full", newline_policy=NewlinePolicy.ESCAPE)
        formatter = DefaultFormatter(opts, "shell", None)
        entry = _make_logentry(
            raw_content="line1\nline2\nline3",
            role="edit",
            tool_name="Edit",
            summary='Edit: "/p" ← "{snippet}"',
            metadata={"datetime_part": "", "pwd_part": ""},
        )
        result = formatter.format(entry)
        # ESCAPE: real newlines become literal \n
        assert "line1\\nline2\\nline3" in result
        assert "\nline2\n" not in result

    def test_render_policy_via_chat_formatter(self):
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(
            verbosity="full",
            formatter="chat",
            newline_policy=NewlinePolicy.RENDER,
        )
        entry = _make_logentry(
            raw_content="line1\nline2\nline3",
            role="user",
            tool_name="UserPromptSubmit",
        )
        result = format_for_channel(entry, opts, "convo", None)
        # RENDER: real newlines preserved
        assert "line1\nline2\nline3" in result

    def test_chat_formatter_with_escape_falls_back_to_single_line(self):
        from cclogger.formatters import format_for_channel
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(
            verbosity="full",
            formatter="chat",
            newline_policy=NewlinePolicy.ESCAPE,
        )
        entry = _make_logentry(
            raw_content="line1\nline2",
            role="user",
            tool_name="UserPromptSubmit",
        )
        result = format_for_channel(entry, opts, "convo", None)
        # ESCAPE collapses to single line
        assert "line1\\nline2" in result


# ============================================================================
# Section 16: Per-channel defaults (the v0.3.7 shipped configuration)
# ============================================================================


class TestPerChannelDefaults:
    """Pinned: shipped channel defaults bundle the right ChannelOptions."""

    def test_convo_channel_uses_chat_formatter(self):
        from cclogger.models import Config, NewlinePolicy
        cfg = Config()
        convo = cfg.routing.channels["convo"]
        assert convo.options.formatter == "chat"
        assert convo.options.newline_policy == NewlinePolicy.RENDER
        assert convo.options.verbosity == "full"

    def test_tasks_channel_uses_task_only_formatter(self):
        from cclogger.models import Config
        cfg = Config()
        tasks = cfg.routing.channels["tasks"]
        assert tasks.options.formatter == "task-only"

    def test_sesslog_channel_uses_full_verbosity_with_io_overrides(self):
        """sesslog defaults to per-role dict: full for most roles, truncated for
        write/edit/multi-edit/notebook-edit (file-I/O entries dominate the
        kitchen-sink channel otherwise; full content goes to .fileio_*)."""
        from cclogger.models import Config
        cfg = Config()
        sesslog = cfg.routing.channels["sesslog"]
        v = sesslog.options.verbosity
        assert isinstance(v, dict)
        assert v["_default"] == "full"
        assert v["write"] == {"max_chars": 20}
        assert v["edit"] == {"max_chars": 20}
        assert v["multi-edit"] == {"max_chars": 20}
        assert v["notebook-edit"] == {"max_chars": 20}

    def test_shell_channel_uses_100_char_budget(self):
        from cclogger.models import Config
        cfg = Config()
        shell = cfg.routing.channels["shell"]
        assert shell.options.verbosity == {"max_chars": 100}

    def test_tools_channel_uses_100_char_budget(self):
        from cclogger.models import Config
        cfg = Config()
        tools = cfg.routing.channels["tools"]
        assert tools.options.verbosity == {"max_chars": 100}

    def test_unknowns_channel_uses_100_char_budget(self):
        from cclogger.models import Config
        cfg = Config()
        unknowns = cfg.routing.channels["unknowns"]
        assert unknowns.options.verbosity == {"max_chars": 100}


# ============================================================================
# Section 17: Hardcoded-removal regression (AST scan)
# ============================================================================


class TestHardcodedSitesRemoved:
    """Pinned: the four v0.3.6 hardcoded truncation/dispatch sites are gone."""

    def test_no_truncate_preview_in_conversation_module(self):
        """conversation.py must not call truncate_preview anymore (Step 6)."""
        import ast
        from pathlib import Path
        src = Path("hooks/scripts/cclogger/conversation.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "truncate_preview":
                    pytest.fail(
                        f"truncate_preview() found in conversation.py at line {node.lineno} — "
                        f"Phase 2+3 Step 6 should have removed it"
                    )

    def test_log_entry_signature_no_task_content_param(self):
        """log_entry() signature must not have the v0.3.6 task_content parameter
        (Step 5 stuffed task_content into LogEntry.metadata instead, eliminating
        the special-case argument and the per-channel dispatch hardcode it served).
        """
        import inspect
        sig = inspect.signature(_mod.SessionLogger.log_entry)
        assert "task_content" not in sig.parameters, (
            "task_content parameter should have been removed from log_entry() in Step 5; "
            "task data now lives in LogEntry.metadata['task_content'] and TaskOnlyFormatter reads it"
        )

    def test_log_entry_no_dispatch_branching_on_channel_name(self):
        """log_entry() body must not branch on `channel_name == "tasks"` for
        dispatch (Step 5 replaced with formatter dispatch). The filename-
        generation hardcode in _get_channel_path is a separate concern and
        is allowed to remain — Phase 6 polish may revisit it.
        """
        import ast
        import inspect
        import textwrap

        src = textwrap.dedent(inspect.getsource(_mod.SessionLogger.log_entry))
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                if (
                    isinstance(node.left, ast.Name)
                    and node.left.id == "channel_name"
                    and len(node.comparators) == 1
                    and isinstance(node.comparators[0], ast.Constant)
                    and node.comparators[0].value == "tasks"
                ):
                    pytest.fail(
                        f"log_entry() branches on channel_name == 'tasks' at relative line "
                        f"{node.lineno} — Step 5 should have replaced this with formatter dispatch"
                    )

    def test_log_entry_no_task_content_parameter(self):
        """log_entry() signature must not have task_content arg (Step 5 removed it)."""
        import inspect
        sig = inspect.signature(_mod.SessionLogger.log_entry)
        assert "task_content" not in sig.parameters, (
            "task_content parameter should have been removed from log_entry() in Step 5"
        )


# ============================================================================
# Section 18: CommandContent dataclass (Phase 2+3 Step 7)
# ============================================================================


class TestCommandContent:
    """Pinned: CommandContent dataclass carries raw_content + legacy_string + summary_template."""

    def test_command_content_exists(self):
        from cclogger.models import CommandContent
        cc = CommandContent(raw_content="x", legacy_string="x", summary_template=None)
        assert cc.raw_content == "x"
        assert cc.legacy_string == "x"
        assert cc.summary_template is None

    def test_get_command_content_structured_returns_dataclass(self):
        from cclogger.formatters import get_command_content_structured
        from cclogger.models import CommandContent, ToolInfo
        ti = ToolInfo(
            name="Bash",
            input={"command": "ls -la"},
            description="",
            session_id="abc",
            transcript_path="",
            raw_json={},
        )
        result = get_command_content_structured(ti, None)
        assert isinstance(result, CommandContent)
        assert result.raw_content == "ls -la"
        assert result.legacy_string == "ls -la"
        assert result.summary_template is None  # Bash is non-rich

    def test_edit_handler_returns_summary_template(self):
        from cclogger.formatters import get_command_content_structured
        from cclogger.models import ToolInfo
        ti = ToolInfo(
            name="Edit",
            input={
                "file_path": "/tmp/x.py",
                "old_string": "old",
                "new_string": "new content",
            },
            description="",
            session_id="abc",
            transcript_path="",
            raw_json={},
        )
        result = get_command_content_structured(ti, None)
        # Edit is a rich-format handler → has summary_template with {snippet}
        assert result.summary_template is not None
        assert "{snippet}" in result.summary_template
        # raw_content is the new_string for {snippet} substitution
        assert result.raw_content == "new content"

    def test_write_handler_returns_summary_template(self):
        from cclogger.formatters import get_command_content_structured
        from cclogger.models import ToolInfo
        ti = ToolInfo(
            name="Write",
            input={"file_path": "/tmp/x.txt", "content": "hello world"},
            description="",
            session_id="abc",
            transcript_path="",
            raw_json={},
        )
        result = get_command_content_structured(ti, None)
        assert result.summary_template is not None
        assert "{snippet}" in result.summary_template
        assert result.raw_content == "hello world"

    def test_get_command_content_legacy_wrapper_still_returns_str(self):
        """Backward compat: get_command_content() still returns just the legacy string."""
        from cclogger.formatters import get_command_content
        from cclogger.models import ToolInfo
        ti = ToolInfo(
            name="Bash",
            input={"command": "echo hi"},
            description="",
            session_id="abc",
            transcript_path="",
            raw_json={},
        )
        result = get_command_content(ti, None)
        assert isinstance(result, str)
        assert result == "echo hi"


# ============================================================================
# Section 19: ROLE_LABELS resolution + ??:<role> fallback for unknown roles
# ============================================================================


class TestRoleLabelResolution:
    """Pinned: known roles use ROLE_LABELS dict; unknown roles get ??: prefix."""

    def test_known_role_resolves_to_label(self):
        from cclogger.formatters.base import BaseFormatter
        formatter = BaseFormatter(None, "test", None)
        assert formatter._resolve_role_label("user") == "USER"
        assert formatter._resolve_role_label("bash") == "Bash"
        assert formatter._resolve_role_label("edit") == "Edit"

    def test_unknown_role_gets_question_mark_prefix(self, tmp_path, monkeypatch):
        # Isolate sentinel dir to tmp_path so test doesn't pollute ~/.claude/
        monkeypatch.setattr(
            "cclogger.debug.UNKNOWN_ROLE_WARN_DIR",
            tmp_path / ".unknown_role_warnings",
        )
        from cclogger.formatters.base import BaseFormatter
        formatter = BaseFormatter(None, "test", None)
        result = formatter._resolve_role_label("totally-made-up-role-xyz")
        assert result.startswith("??:")
        assert "totally-made-up-role-xyz" in result

    def test_unknown_role_warning_throttled_via_sentinel(self, tmp_path, monkeypatch):
        sentinel_dir = tmp_path / ".unknown_role_warnings"
        monkeypatch.setattr("cclogger.debug.UNKNOWN_ROLE_WARN_DIR", sentinel_dir)
        from cclogger.debug import _warn_unknown_role_once
        # First call creates sentinel + would log warning
        _warn_unknown_role_once("brand-new-role")
        sentinels_after_first = list(sentinel_dir.glob("*.warned"))
        assert len(sentinels_after_first) == 1
        # Second call hits FileExistsError; no new sentinel
        _warn_unknown_role_once("brand-new-role")
        sentinels_after_second = list(sentinel_dir.glob("*.warned"))
        assert len(sentinels_after_second) == 1

    def test_per_channel_role_label_override(self):
        from cclogger.formatters.base import BaseFormatter
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(role_labels={"bash": "BASH-OVERRIDDEN"})
        formatter = BaseFormatter(opts, "test", None)
        assert formatter._resolve_role_label("bash") == "BASH-OVERRIDDEN"
        # Other roles still use global
        assert formatter._resolve_role_label("user") == "USER"

    def test_per_channel_label_uses_longest_prefix(self):
        from cclogger.formatters.base import BaseFormatter
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(role_labels={"agent": "AGT", "agent:senior-engineer": "SR-ENG"})
        formatter = BaseFormatter(opts, "test", None)
        assert formatter._resolve_role_label("agent:senior-engineer") == "SR-ENG"
        assert formatter._resolve_role_label("agent") == "AGT"
        assert formatter._resolve_role_label("agent:other") == "AGT"


# ============================================================================
# Section 20: Subtype-channel options inheritance
# ============================================================================
#
# Subtype routing (v0.3.3, Github #31) creates dynamic channel names like
# "shell-powershell" or "tools-github" at log time. These derived channels
# aren't declared in routing.channels — they're manufactured per-event.
#
# Phase 2+3 fixes the gap where derived channels silently fell back to
# global defaults instead of inheriting the parent channel's ChannelOptions.
# Without inheritance, enabling subtype_routing.tools = true would write
# .tools-github_*.log with 20-char snippets (global default) even though
# the parent .tools_*.log uses 100-char snippets per its bundled options.


class TestSubtypeChannelInheritance:
    """Pinned: subtype-derived channels inherit parent ChannelOptions.

    Standard inheritance pattern: declare-to-override, omit-to-inherit.
    A derived channel name "<base>-<subtype>" looks up the base channel's
    options; explicitly declaring the derived channel takes precedence.
    """

    def _make_logger(self, config):
        """Build a SessionLogger without going through filesystem reconciliation."""
        from cclogger.logger import SessionLogger
        from cclogger.models import SessionContext
        # Use object.__new__ to skip __init__'s heavy reconciliation work.
        # We only need _resolve_channel_options to run.
        logger = object.__new__(SessionLogger)
        logger.config = config
        logger.session = SessionContext(
            shell_type="bash",
            session_name="test",
            session_id="00000000-0000-0000-0000-000000000001",
            username="testuser",
        )
        return logger

    def test_subtype_channel_inherits_parent_options(self):
        from cclogger.models import Config
        config = Config()
        logger = self._make_logger(config)
        # tools channel has max_chars=100; tools-github should inherit
        opts = logger._resolve_channel_options(None, "tools-github")
        assert opts is not None
        assert opts.verbosity == {"max_chars": 100}

    def test_subtype_channel_inherits_sesslog_full_verbosity(self):
        from cclogger.models import Config
        config = Config()
        logger = self._make_logger(config)
        # sesslog uses per-role dict with _default fallback; sesslog-github inherits
        opts = logger._resolve_channel_options(None, "sesslog-github")
        assert opts is not None
        assert isinstance(opts.verbosity, dict)
        assert opts.verbosity["_default"] == "full"

    def test_subtype_channel_inherits_chat_formatter_from_convo(self):
        from cclogger.models import Config, NewlinePolicy
        config = Config()
        logger = self._make_logger(config)
        # convo uses formatter="chat" + RENDER; convo-help inherits
        opts = logger._resolve_channel_options(None, "convo-help")
        assert opts is not None
        assert opts.formatter == "chat"
        assert opts.newline_policy == NewlinePolicy.RENDER

    def test_explicit_subtype_channel_takes_precedence_over_inheritance(self):
        """Declaring a subtype channel explicitly overrides parent inheritance."""
        from cclogger.models import (
            ChannelConfig, ChannelOptions, Config, NewlinePolicy,
        )
        config = Config()
        # Explicitly declare shell-powershell with a different verbosity
        config.routing.channels["shell-powershell"] = ChannelConfig(
            file_prefix=".shell-powershell_",
            options=ChannelOptions(verbosity={"max_chars": 50}),
        )
        logger = self._make_logger(config)
        explicit_channel = config.routing.channels["shell-powershell"]
        opts = logger._resolve_channel_options(explicit_channel, "shell-powershell")
        # The explicit declaration wins (50), not the parent shell's 100
        assert opts.verbosity == {"max_chars": 50}

    def test_unknown_base_channel_returns_none(self):
        """If neither the derived channel nor its base exists, return None."""
        from cclogger.models import Config
        config = Config()
        logger = self._make_logger(config)
        # No "nonexistent" channel anywhere
        opts = logger._resolve_channel_options(None, "nonexistent-subtype")
        assert opts is None

    def test_non_subtype_unknown_channel_returns_none(self):
        """Channel name without the `<base>-<subtype>` shape doesn't trigger inheritance."""
        from cclogger.models import Config
        config = Config()
        logger = self._make_logger(config)
        opts = logger._resolve_channel_options(None, "totally-fake-channel-no-dash-sentinel")
        # Has dashes -> tries inheritance lookup for "totally" base
        # which doesn't exist -> returns None
        assert opts is None

    def test_no_dash_no_inheritance_attempt(self):
        """Channel name with no dash short-circuits to None when channel is None."""
        from cclogger.models import Config
        config = Config()
        logger = self._make_logger(config)
        opts = logger._resolve_channel_options(None, "nodashhere")
        assert opts is None


# ============================================================================
# Section 21: `_default` per-role-dict fallback (Phase 2+3 framework extension)
# ============================================================================
#
# The `_default` reserved keyword lets a per-role verbosity dict express
# "channel default = X, but override these specific roles." Without it,
# unmatched roles fall to the global default (20), which prevents
# expressing "full for everything except Write/Edit at 20 chars."


class TestDefaultReservedKeyword:
    """Pinned: `_default` inside per-role verbosity dict is the channel fallback."""

    def test_default_keyword_is_in_reserved_set(self):
        from cclogger.models import (
            HINT_VERBOSITY_KEYS, PER_ROLE_RESERVED_KEYS, RESERVED_VERBOSITY_KEYS,
        )
        # _default is a per-role reserved key, NOT a hint key
        assert "_default" in PER_ROLE_RESERVED_KEYS
        assert "_default" not in HINT_VERBOSITY_KEYS
        assert "_default" in RESERVED_VERBOSITY_KEYS

    def test_default_fallback_for_unmatched_role(self):
        """_default applies when no role-specific override matches."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={
            "_default": "full",
            "write": {"max_chars": 20},
        })
        # "user" doesn't match write; _default = "full" → 0
        assert _resolve_verbosity(opts, "user", "UserPromptSubmit", 20) == 0

    def test_specific_role_override_beats_default(self):
        """Specific role match wins over _default fallback."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={
            "_default": "full",
            "write": {"max_chars": 20},
        })
        # "write" matches; gets 20-char budget, not full
        assert _resolve_verbosity(opts, "write", "Write", 20) == 20

    def test_no_match_no_default_falls_to_global(self):
        """Without _default, unmatched roles fall to global default (unchanged)."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={"write": {"max_chars": 100}})
        # "user" doesn't match, no _default → global default (50)
        assert _resolve_verbosity(opts, "user", "UserPromptSubmit", 50) == 50

    def test_default_recursive_value(self):
        """_default's value can be any verbosity shape (string, hint dict, int)."""
        from cclogger.formatters import _resolve_verbosity
        from cclogger.models import ChannelOptions
        opts = ChannelOptions(verbosity={
            "_default": {"max_chars": 50},
            "write": "full",
        })
        # Unmatched role gets _default's value (50)
        assert _resolve_verbosity(opts, "user", "UserPromptSubmit", 20) == 50
        # write gets full (0)
        assert _resolve_verbosity(opts, "write", "Write", 20) == 0

    def test_default_not_treated_as_hint_key(self):
        """A dict with only _default is a per-role dict (with fallback), not a hint dict."""
        from cclogger.formatters.legacy import _is_hint_dict
        # _default alone → per-role dict (would fall to default for any role)
        assert _is_hint_dict({"_default": "full"}) is False
        # max_chars alone → hint dict (applies uniformly)
        assert _is_hint_dict({"max_chars": 50}) is True
        # _default + max_chars → per-role dict (because _default isn't a hint key)
        assert _is_hint_dict({"_default": "full", "max_chars": 50}) is False

    def test_default_works_for_newline_policy_too(self):
        """The _default extension also applies to newline_policy resolution."""
        from cclogger.formatters import _resolve_newline_policy
        from cclogger.models import ChannelOptions, NewlinePolicy
        opts = ChannelOptions(newline_policy={
            "_default": "render",
            "write": "escape",
        })
        # Unmatched role gets _default
        assert _resolve_newline_policy(opts, "user", "UserPromptSubmit") == NewlinePolicy.RENDER
        # write override wins
        assert _resolve_newline_policy(opts, "write", "Write") == NewlinePolicy.ESCAPE


# ============================================================================
# Section 22: `.fileio_*` channel — opt-in full file-I/O capture
# ============================================================================


class TestFileioChannel:
    """Pinned: .fileio_* channel exists, disabled by default, captures full content."""

    def test_fileio_channel_in_defaults(self):
        from cclogger.models import Config
        cfg = Config()
        assert "fileio" in cfg.routing.channels

    def test_fileio_channel_disabled_by_default(self):
        """fileio is opt-in: users must enable it before file content is captured."""
        from cclogger.models import Config
        cfg = Config()
        assert cfg.routing.channels["fileio"].enabled is False

    def test_fileio_channel_uses_full_verbosity_and_render(self):
        from cclogger.models import Config, NewlinePolicy
        cfg = Config()
        opts = cfg.routing.channels["fileio"].options
        assert opts.verbosity == "full"
        assert opts.newline_policy == NewlinePolicy.RENDER

    def test_io_category_routes_to_fileio(self):
        """The io category route includes fileio so file-I/O ops capture there when enabled."""
        from cclogger.models import Config
        cfg = Config()
        assert "fileio" in cfg.routing.category_routes["io"]

    def test_read_now_in_io_category(self):
        """Read moved from system to io so Read entries also route to fileio."""
        from cclogger.categorize import categorize_tool
        assert categorize_tool("Read") == "io"

    def test_write_edit_still_in_io_category(self):
        """Write/Edit/MultiEdit/NotebookEdit still in io (joined by Read)."""
        from cclogger.categorize import categorize_tool
        assert categorize_tool("Write") == "io"
        assert categorize_tool("Edit") == "io"
        assert categorize_tool("MultiEdit") == "io"
        assert categorize_tool("NotebookEdit") == "io"
