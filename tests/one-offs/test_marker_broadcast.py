"""Phase 4 (Github #39) — session-start / compaction marker broadcast.

Verifies that `_maybe_write_session_marker` writes the visual marker to every
enabled channel whose `ChannelOptions.suppress_markers` is False, that
suppression opts a channel out, that disabled channels are skipped, that
subtype-derived channels are deliberately excluded, and that the run-counter
authority stays on the sesslog path.

Tests bypass the marker primitive (`write_session_marker`) — already covered
in Phase 0 — and target the broadcast policy specifically.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect HOME/USERPROFILE so session-states + sesslogs land in tmp_path.

    SessionLogger reads from `Path.home() / ".claude"` for both the state
    directory (.started flag) and the sesslogs root. Redirecting via env vars
    ensures the test does not touch the developer's real `~/.claude/`.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # On Windows, Path.home() reads USERPROFILE; on POSIX, HOME. Cover both.
    return tmp_path


@pytest.fixture
def fresh_session(isolated_home):
    """Build a SessionContext + Config and return (config, session, event_time).

    Each test gets a unique session_id so the `.started` flag does not persist
    across tests within the same isolated_home.
    """
    from cclogger.models import Config, SessionContext

    session = SessionContext(
        shell_type="bash.exe",
        session_name="phase4-marker-test",
        session_id=f"test-session-{id(isolated_home)}",
        username="testuser",
    )
    config = Config()  # defaults
    event_time = datetime(2026, 5, 12, 12, 0, 0)
    return config, session, event_time


def _instantiate(config, session, event_time):
    """Construct a SessionLogger — `__init__` writes markers as a side effect."""
    from cclogger.logger import SessionLogger
    return SessionLogger(config, session, event_time)


def _read_marker_count(path: Path) -> int:
    if not path.exists():
        return 0
    return path.read_text(encoding="utf-8", errors="replace").count("═══ SESSION START")


# ============================================================================
# Section 23: Broadcast covers all enabled channels by default
# ============================================================================


class TestBroadcastToAllEnabledChannels:
    """All enabled channels (not just shell + sesslog) receive markers."""

    def test_default_channels_all_receive_session_start_marker(self, fresh_session):
        config, session, event_time = fresh_session
        logger = _instantiate(config, session, event_time)

        # Default channels with enabled=True: shell, sesslog, tasks, unknowns, tools, convo
        # (fileio is enabled=False by default — should NOT have marker)
        expected_channels = ["shell", "sesslog", "tasks", "unknowns", "tools", "convo"]
        for channel_name in expected_channels:
            path = logger._get_channel_path(channel_name)
            count = _read_marker_count(path)
            assert count == 1, f"{channel_name}: expected 1 marker, got {count} at {path}"

    def test_disabled_channel_receives_no_marker(self, fresh_session):
        """fileio is enabled=False by default — no marker file should be created for it."""
        config, session, event_time = fresh_session
        logger = _instantiate(config, session, event_time)

        path = logger._get_channel_path("fileio")
        assert _read_marker_count(path) == 0, "fileio is disabled — no marker expected"

    def test_enabling_fileio_includes_it_in_broadcast(self, fresh_session):
        config, session, event_time = fresh_session
        config.routing.channels["fileio"].enabled = True

        logger = _instantiate(config, session, event_time)
        path = logger._get_channel_path("fileio")
        assert _read_marker_count(path) == 1, "fileio is now enabled — should receive marker"


# ============================================================================
# Section 24: suppress_markers opt-out
# ============================================================================


class TestSuppressMarkersOptOut:
    """ChannelOptions.suppress_markers=True keeps a channel marker-free."""

    def test_suppress_markers_on_convo_excludes_convo(self, fresh_session):
        config, session, event_time = fresh_session
        config.routing.channels["convo"].options.suppress_markers = True

        logger = _instantiate(config, session, event_time)

        # Sesslog should still get a marker
        assert _read_marker_count(logger.unified_log_path) == 1
        # Convo should be marker-free
        convo_path = logger._get_channel_path("convo")
        assert _read_marker_count(convo_path) == 0

    def test_suppress_markers_on_all_channels_writes_nothing(self, fresh_session):
        config, session, event_time = fresh_session
        for channel in config.routing.channels.values():
            channel.options.suppress_markers = True

        logger = _instantiate(config, session, event_time)

        # No channel should have a marker
        for channel_name in config.routing.channels:
            if not config.routing.channels[channel_name].enabled:
                continue
            path = logger._get_channel_path(channel_name)
            assert _read_marker_count(path) == 0, (
                f"{channel_name} should be marker-free with suppress_markers=True"
            )


# ============================================================================
# Section 25: Subtype-derived channels stay clean
# ============================================================================


class TestSubtypeDerivedChannelsExcluded:
    """`.bash-powershell_*` and friends are derived lazily; markers skip them.

    Even if subtype routing is enabled, the marker broadcast only iterates
    top-level declared channels in routing.channels. Subtype channels appear
    on first matching tool call, not at session-start time.
    """

    def test_subtype_routing_enabled_does_not_create_subtype_marker(self, fresh_session):
        config, session, event_time = fresh_session
        # v0.3.7-pre: subtype splitting moved from category-wide
        # `routing.subtype_routing["bash"]` to per-channel
        # `routing.channels[name].options.subtype_split`. Same intent here:
        # opt shell into subtype splitting, then verify subtype-derived
        # channels are still excluded from marker broadcast.
        config.routing.channels["shell"].options.subtype_split = True

        logger = _instantiate(config, session, event_time)

        # The derived path `.bash-powershell_*` should NOT exist (no marker file)
        target_paths = logger._collect_marker_target_paths()
        for path in target_paths:
            assert "-" not in path.name.split("_")[0], (
                f"Subtype-derived path slipped into broadcast: {path}"
            )


# ============================================================================
# Section 26: Run-counter authority stays sesslog
# ============================================================================


class TestRunCounterAuthority:
    """`get_run_number` reads from the unified sesslog regardless of where
    markers were broadcast. Broadcasting to multiple channels must not inflate
    the run count.
    """

    def test_run_number_increments_from_sesslog_marker_count(self, fresh_session, isolated_home):
        from cclogger.markers import count_session_markers

        config, session, event_time = fresh_session

        # First session — should write Run #1 to all enabled channels
        logger1 = _instantiate(config, session, event_time)
        sesslog_count_after_run1 = count_session_markers(logger1.unified_log_path)
        assert sesslog_count_after_run1 == 1

        # Tools channel also got a marker, but the run counter ignores it
        tools_path = logger1._get_channel_path("tools")
        assert _read_marker_count(tools_path) == 1

        # Simulate a new session run: clear the .started flag and run-number cache
        state_dir = isolated_home / ".claude" / "session-states"
        for suffix in (".started", ".run"):
            f = state_dir / f"{session.session_id}{suffix}"
            if f.exists():
                f.unlink()

        # Second session — sesslog has 1 marker, so this run should be Run #2
        logger2 = _instantiate(config, session, datetime(2026, 5, 12, 13, 0, 0))
        sesslog_count_after_run2 = count_session_markers(logger2.unified_log_path)
        assert sesslog_count_after_run2 == 2

        # Tools channel now has 2 markers too (Run #1 + Run #2 broadcast),
        # but the run counter ALWAYS reads sesslog — so even if tools had
        # 100 markers from a different code path, sesslog would still be the
        # authoritative source. This is by design (single source of truth).
        assert _read_marker_count(tools_path) == 2

    def test_disabling_sesslog_does_not_corrupt_run_counter(self, fresh_session, isolated_home):
        """Edge case: if a user disables sesslog, run counting reads a non-
        existent file → returns 0 → next run number is 1 forever. This is the
        documented limitation of run-counter-on-sesslog; the test pins it.
        """
        from cclogger.markers import count_session_markers

        config, session, event_time = fresh_session
        config.routing.channels["sesslog"].enabled = False

        logger = _instantiate(config, session, event_time)

        # Sesslog is disabled, so no file created → count is 0
        assert count_session_markers(logger.unified_log_path) == 0
        # But other channels DID get a Run #1 marker
        assert _read_marker_count(logger._get_channel_path("shell")) == 1
