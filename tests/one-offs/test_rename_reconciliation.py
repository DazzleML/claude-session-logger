"""Tests: rename reconciliation enumerates all channels + subtype derivs (Bug B).

v0.3.7-pre fix for the pre-existing bug where `reconcile_session_files`
hardcoded `["sesslog", "shell", "tasks"]` and orphaned every other channel
(tools, convo, unknowns, agents, fileio) plus all subtype derivatives on
session rename. Also covers the one-time `sweep_orphan_session_name_files`
that moves pre-existing orphans to `<session_dir>/baks/`.

Run: python -m pytest tests/one-offs/test_rename_reconciliation.py -v
"""

from __future__ import annotations

from pathlib import Path

from cclogger.file_io import (
    ORPHAN_SWEEP_SENTINEL,
    sweep_orphan_session_name_files,
    _embedded_session_name,
)
from cclogger.reconciliation import (
    _rename_files_for_session_change,
    discover_channel_basenames,
    reconcile_session_files,
)


# ============================================================================
# Helpers
# ============================================================================

SESSION_ID = "abcd1234-5678-9012-3456-7890abcdef00"
USER = "tester"
SHELL = "bash.exe"


def _make_log(directory: Path, basename: str, session_name: str | None) -> Path:
    """Create a fake log file in the directory matching the structural pattern."""
    if session_name is None:
        # Unnamed form: .<basename>_<shell>_<guid>_<user>.log
        name = f".{basename}_{SHELL}_{SESSION_ID}_{USER}.log"
    else:
        name = f".{basename}_{SHELL}__{session_name}__{SESSION_ID}_{USER}.log"
    path = directory / name
    path.write_text("synthetic log content\n", encoding="utf-8")
    return path


# ============================================================================
# discover_channel_basenames
# ============================================================================


class TestDiscoverChannelBasenames:
    def test_empty_dir_returns_empty_set(self, tmp_path):
        assert discover_channel_basenames(tmp_path, SESSION_ID) == set()

    def test_finds_declared_channel_basenames(self, tmp_path):
        _make_log(tmp_path, "sesslog", "myname")
        _make_log(tmp_path, "shell", "myname")
        _make_log(tmp_path, "tools", "myname")
        names = discover_channel_basenames(tmp_path, SESSION_ID)
        assert names == {"sesslog", "shell", "tools"}

    def test_finds_subtype_derived_basenames(self, tmp_path):
        _make_log(tmp_path, "shell", "myname")
        _make_log(tmp_path, "shell-bash", "myname")
        _make_log(tmp_path, "shell-grep", "myname")
        _make_log(tmp_path, "agents-help", "myname")
        names = discover_channel_basenames(tmp_path, SESSION_ID)
        assert names == {"shell", "shell-bash", "shell-grep", "agents-help"}

    def test_skips_files_without_session_guid(self, tmp_path):
        _make_log(tmp_path, "sesslog", "myname")
        # Foreign session UUID
        foreign = tmp_path / f".sesslog_bash.exe__myname__different-uuid_{USER}.log"
        foreign.write_text("noise\n", encoding="utf-8")
        names = discover_channel_basenames(tmp_path, SESSION_ID)
        assert names == {"sesslog"}

    def test_skips_non_log_files(self, tmp_path):
        _make_log(tmp_path, "sesslog", "myname")
        (tmp_path / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
        # Both new-named and legacy sentinel files; should be ignored
        (tmp_path / ".session-logger-orphans-swept").write_text("", encoding="utf-8")
        (tmp_path / ".session-logger-overflow-migrated").write_text("", encoding="utf-8")
        (tmp_path / ".orphan_session_name_swept_v0.3.7").write_text("", encoding="utf-8")
        (tmp_path / ".overflow_migrated_v0.3.7").write_text("", encoding="utf-8")
        (tmp_path / "README.session-logger.md").write_text("# stub\n", encoding="utf-8")
        names = discover_channel_basenames(tmp_path, SESSION_ID)
        assert names == {"sesslog"}


# ============================================================================
# _rename_files_for_session_change — Bug B regression
# ============================================================================


class TestRenameAllChannels:
    """The pre-fix code only renamed .sesslog_/.shell_/.tasks_. Verify the
    new code walks every log file matching the structural pattern."""

    def test_renames_declared_non_legacy_channels(self, tmp_path):
        """tools/convo/unknowns/agents/fileio must all get renamed too."""
        for ch in ("tools", "convo", "unknowns", "agents", "fileio"):
            _make_log(tmp_path, ch, "oldname")
        _rename_files_for_session_change(tmp_path, "oldname", "newname", SESSION_ID)
        renamed = sorted(p.name for p in tmp_path.iterdir())
        for ch in ("tools", "convo", "unknowns", "agents", "fileio"):
            new_pattern = f".{ch}_{SHELL}__newname__{SESSION_ID}_{USER}.log"
            old_pattern = f".{ch}_{SHELL}__oldname__{SESSION_ID}_{USER}.log"
            assert new_pattern in renamed, (
                f"{ch} not renamed; got {renamed}"
            )
            assert old_pattern not in renamed, (
                f"{ch} old-name file still present; got {renamed}"
            )

    def test_renames_subtype_derived_siblings(self, tmp_path):
        """Subtype derivatives discovered on disk get renamed too."""
        _make_log(tmp_path, "shell-bash", "oldname")
        _make_log(tmp_path, "shell-grep", "oldname")
        _make_log(tmp_path, "agents-help", "oldname")
        _make_log(tmp_path, "tools-powershell", "oldname")
        _rename_files_for_session_change(tmp_path, "oldname", "newname", SESSION_ID)
        renamed = sorted(p.name for p in tmp_path.iterdir())
        for ch in ("shell-bash", "shell-grep", "agents-help", "tools-powershell"):
            assert any(
                ch in n and "newname" in n and "oldname" not in n
                for n in renamed
            ), f"subtype {ch} not renamed; got {renamed}"

    def test_skips_transcript_jsonl_and_sentinels(self, tmp_path):
        """Non-log files (transcript.jsonl, sentinels, README) must NOT be touched."""
        _make_log(tmp_path, "sesslog", "oldname")
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")
        sentinel = tmp_path / ORPHAN_SWEEP_SENTINEL
        sentinel.write_text("", encoding="utf-8")
        overflow_sentinel = tmp_path / ".session-logger-overflow-migrated"
        overflow_sentinel.write_text("", encoding="utf-8")
        legacy_sentinel = tmp_path / ".overflow_migrated_v0.3.7"
        legacy_sentinel.write_text("", encoding="utf-8")
        readme = tmp_path / "README.session-logger.md"
        readme.write_text("# stub\n", encoding="utf-8")

        _rename_files_for_session_change(tmp_path, "oldname", "newname", SESSION_ID)

        # Non-log files survived unchanged
        assert transcript.exists()
        assert sentinel.exists()
        assert overflow_sentinel.exists()
        assert legacy_sentinel.exists()
        assert readme.exists()
        # Sesslog was renamed
        expected = tmp_path / f".sesslog_{SHELL}__newname__{SESSION_ID}_{USER}.log"
        assert expected.exists()

    def test_unnamed_to_named_transition(self, tmp_path):
        """Files with no embedded name get the new name inserted."""
        _make_log(tmp_path, "sesslog", None)  # unnamed form
        _make_log(tmp_path, "tools", None)
        _make_log(tmp_path, "shell-bash", None)
        _rename_files_for_session_change(tmp_path, None, "newname", SESSION_ID)
        renamed = sorted(p.name for p in tmp_path.iterdir())
        for ch in ("sesslog", "tools", "shell-bash"):
            expected = f".{ch}_{SHELL}__newname__{SESSION_ID}_{USER}.log"
            assert expected in renamed, f"{ch} not renamed to named form; got {renamed}"


# ============================================================================
# reconcile_session_files — channel_names enumeration
# ============================================================================


class TestReconcileSessionFilesEnumeration:
    def test_renames_only_declared_channels_returned_in_targets(self, tmp_path):
        """Subtype derivatives are reconciled in-place but NOT in the
        returned target-paths dict (they materialize lazily on next write)."""
        _make_log(tmp_path, "sesslog", "oldname")
        _make_log(tmp_path, "tools", "oldname")
        _make_log(tmp_path, "shell-bash", "oldname")

        targets = reconcile_session_files(
            tmp_path, SESSION_ID, "newname", SHELL, USER,
            channel_names=["sesslog", "shell", "tools"],
        )

        # Declared channels are in the dict
        assert "sesslog" in targets
        assert "tools" in targets
        # Subtype derivative is NOT in the dict
        assert "shell-bash" not in targets
        assert "shell" in targets  # declared even though no file existed

        # But on disk: subtype derivative IS renamed
        names = sorted(p.name for p in tmp_path.iterdir())
        assert any(
            "shell-bash" in n and "newname" in n for n in names
        ), f"shell-bash subtype not renamed: {names}"

# ============================================================================
# _embedded_session_name helper
# ============================================================================


class TestEmbeddedSessionName:
    def test_extracts_name_from_named_form(self):
        name = f".sesslog_{SHELL}__myname__{SESSION_ID}_{USER}.log"
        assert _embedded_session_name(name, SESSION_ID) == "myname"

    def test_extracts_name_from_subtype_form(self):
        name = f".shell-bash_{SHELL}__myname__{SESSION_ID}_{USER}.log"
        assert _embedded_session_name(name, SESSION_ID) == "myname"

    def test_returns_none_for_unnamed_form(self):
        name = f".sesslog_{SHELL}_{SESSION_ID}_{USER}.log"
        assert _embedded_session_name(name, SESSION_ID) is None

    def test_returns_none_for_foreign_session(self):
        name = f".sesslog_{SHELL}__myname__different-id_{USER}.log"
        assert _embedded_session_name(name, SESSION_ID) is None

    def test_returns_none_for_transcript(self):
        assert _embedded_session_name("transcript.jsonl", SESSION_ID) is None

    def test_strips_sequence_suffix(self):
        name = f".sesslog_{SHELL}__myname--001__{SESSION_ID}_{USER}.log"
        assert _embedded_session_name(name, SESSION_ID) == "myname"


# ============================================================================
# sweep_orphan_session_name_files
# ============================================================================


class TestSweepOrphans:
    def test_no_session_name_is_noop(self, tmp_path):
        _make_log(tmp_path, "sesslog", "anyname")
        moved = sweep_orphan_session_name_files(tmp_path, "", SESSION_ID)
        assert moved == 0
        # No sentinel dropped either when session name is empty
        assert not (tmp_path / ORPHAN_SWEEP_SENTINEL).exists()

    def test_missing_dir_returns_zero(self, tmp_path):
        ghost = tmp_path / "does-not-exist"
        moved = sweep_orphan_session_name_files(ghost, "newname", SESSION_ID)
        assert moved == 0
        assert not ghost.exists()

    def test_no_orphans_drops_sentinel(self, tmp_path):
        _make_log(tmp_path, "sesslog", "newname")
        _make_log(tmp_path, "tools", "newname")
        moved = sweep_orphan_session_name_files(tmp_path, "newname", SESSION_ID)
        assert moved == 0
        assert (tmp_path / ORPHAN_SWEEP_SENTINEL).exists()
        # Canonical files untouched
        assert (tmp_path / f".sesslog_{SHELL}__newname__{SESSION_ID}_{USER}.log").exists()

    def test_moves_orphan_to_baks(self, tmp_path):
        # Two orphans (old name) + one canonical (new name)
        orphan1 = _make_log(tmp_path, "sesslog", "OLDNAME")
        orphan2 = _make_log(tmp_path, "tools", "OLDNAME")
        canonical = _make_log(tmp_path, "convo", "newname")

        moved = sweep_orphan_session_name_files(tmp_path, "newname", SESSION_ID)
        assert moved == 2

        # Orphans gone from top level, present in baks/
        assert not orphan1.exists()
        assert not orphan2.exists()
        assert (tmp_path / "baks" / orphan1.name).exists()
        assert (tmp_path / "baks" / orphan2.name).exists()
        # Canonical untouched
        assert canonical.exists()
        # Sentinel dropped
        assert (tmp_path / ORPHAN_SWEEP_SENTINEL).exists()

    def test_sentinel_prevents_re_run(self, tmp_path):
        """First run sweeps; second run with NEW orphans must skip the scan."""
        _make_log(tmp_path, "sesslog", "OLD1")
        moved1 = sweep_orphan_session_name_files(tmp_path, "newname", SESSION_ID)
        assert moved1 == 1

        # New orphan introduced AFTER sentinel exists
        _make_log(tmp_path, "tools", "OLD2")
        moved2 = sweep_orphan_session_name_files(tmp_path, "newname", SESSION_ID)
        assert moved2 == 0  # sentinel blocked the scan
        # The new orphan is still at the top level (sweep was skipped)
        leftover = tmp_path / f".tools_{SHELL}__OLD2__{SESSION_ID}_{USER}.log"
        assert leftover.exists()

    def test_collision_appends_numeric_suffix(self, tmp_path):
        """baks/ already has a file with the same name -> numeric suffix."""
        orphan = _make_log(tmp_path, "sesslog", "OLDNAME")
        baks = tmp_path / "baks"
        baks.mkdir()
        # Pre-create a collision at baks/<orphan filename>
        (baks / orphan.name).write_text("prior-collision\n", encoding="utf-8")

        moved = sweep_orphan_session_name_files(tmp_path, "newname", SESSION_ID)
        assert moved == 1
        # Collision exists; second copy got .1 suffix
        assert (baks / orphan.name).read_text(encoding="utf-8") == "prior-collision\n"
        assert (baks / f"{orphan.name}.1").exists()

    def test_subtype_derivatives_also_swept(self, tmp_path):
        """Subtype derivatives with old session names are orphans too."""
        orphan_subtype = _make_log(tmp_path, "shell-bash", "OLDNAME")
        canonical_base = _make_log(tmp_path, "shell", "newname")

        moved = sweep_orphan_session_name_files(tmp_path, "newname", SESSION_ID)
        assert moved == 1
        assert not orphan_subtype.exists()
        assert (tmp_path / "baks" / orphan_subtype.name).exists()
        assert canonical_base.exists()
