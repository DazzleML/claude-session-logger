"""Github #47 — append+lock write primitive + overflow migration.

Covers the v0.3.7-pre rewrite of `cclogger/file_io.atomic_append` that
replaced temp-file+rename with POSIX `O_APPEND` / Windows cooperative
sharing-mode opens plus an exclusive byte-0 lock. The fragile rename
primitive failed on Windows when antivirus, Explorer, or user-held
editor handles held read locks on the destination; the append+lock
primitive succeeds because cooperative sharing modes allow concurrent
readers.

Test classes:
  * AppendLockBasic — happy-path writes, gap markers, null-byte stripping
  * RetryAndOverflow — _safe_append_bytes failure triggers retry then overflow
  * Migration — legacy `.overflow.N` files absorbed in mtime order, sentinel
                prevents re-runs, multi-base grouping, missing dir handled
  * EditorHeldFile — append+lock succeeds even when an external reader
                     holds a long-lived read handle on the destination
                     (the user-edit-while-hook-writes failure mode)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from cclogger.file_io import (
    _safe_append_bytes,
    atomic_append,
    migrate_overflow_files,
    OVERFLOW_MIGRATION_SENTINEL,
)


# ============================================================================
# AppendLockBasic
# ============================================================================


class TestAppendLockBasic:
    def test_first_write_creates_file_with_content_and_trailing_newline(self, tmp_path):
        target = tmp_path / "channel.log"
        atomic_append(target, "hello world")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "hello world\n"

    def test_second_write_appends_without_overwriting(self, tmp_path):
        target = tmp_path / "channel.log"
        atomic_append(target, "first")
        atomic_append(target, "second")
        assert target.read_text(encoding="utf-8") == "first\nsecond\n"

    def test_add_gap_inserts_blank_line_before_entry(self, tmp_path):
        target = tmp_path / "channel.log"
        atomic_append(target, "first")
        atomic_append(target, "second", add_gap=True)
        assert target.read_text(encoding="utf-8") == "first\n\nsecond\n"

    def test_null_bytes_stripped_from_content(self, tmp_path):
        target = tmp_path / "channel.log"
        atomic_append(target, "before\x00middle\x00after")
        assert target.read_text(encoding="utf-8") == "beforemiddleafter\n"

    def test_parent_directory_auto_created(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "channel.log"
        atomic_append(target, "entry")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "entry\n"

    def test_unicode_content_round_trips(self, tmp_path):
        target = tmp_path / "channel.log"
        atomic_append(target, "═══ SESSION START ═══")
        assert target.read_text(encoding="utf-8") == "═══ SESSION START ═══\n"


# ============================================================================
# RetryAndOverflow
# ============================================================================


class TestRetryAndOverflow:
    def test_retry_succeeds_on_second_attempt(self, tmp_path, monkeypatch):
        """If first _safe_append_bytes raises but second succeeds, no overflow file is created."""
        target = tmp_path / "channel.log"
        target.write_text("existing\n", encoding="utf-8")

        call_count = {"n": 0}
        real = _safe_append_bytes

        def flaky(path, payload):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("simulated lock failure")
            return real(path, payload)

        # Patch in the file_io module's view of _safe_append_bytes
        monkeypatch.setattr("cclogger.file_io._safe_append_bytes", flaky)
        # Speed up backoff for the test
        monkeypatch.setattr("cclogger.file_io.LOCK_RETRY_BACKOFF_MS", (0, 0, 0))

        atomic_append(target, "new entry")

        assert call_count["n"] == 2
        assert target.read_text(encoding="utf-8") == "existing\nnew entry\n"
        # No overflow files should have been created
        overflow = list(tmp_path.glob("*.overflow.*"))
        assert overflow == [], f"Unexpected overflow files: {overflow}"

    def test_all_retries_fail_writes_to_overflow(self, tmp_path, monkeypatch):
        target = tmp_path / "channel.log"
        target.write_text("existing\n", encoding="utf-8")

        def always_fail(path, payload):
            raise OSError("simulated persistent lock failure")

        monkeypatch.setattr("cclogger.file_io._safe_append_bytes", always_fail)
        monkeypatch.setattr("cclogger.file_io.LOCK_RETRY_BACKOFF_MS", (0, 0, 0))

        atomic_append(target, "stranded entry")

        # Main file untouched
        assert target.read_text(encoding="utf-8") == "existing\n"
        # Overflow file created with the entry
        overflow_path = tmp_path / "channel.log.overflow.1"
        assert overflow_path.exists()
        assert "stranded entry" in overflow_path.read_text(encoding="utf-8")

    def test_overflow_picks_next_n_when_first_full(self, tmp_path, monkeypatch):
        """If .overflow.1 is over the size threshold, write to .overflow.2."""
        target = tmp_path / "channel.log"
        full_overflow = tmp_path / "channel.log.overflow.1"
        full_overflow.write_bytes(b"x" * 1_100_000)  # > 1MB threshold

        monkeypatch.setattr(
            "cclogger.file_io._safe_append_bytes",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("nope")),
        )
        monkeypatch.setattr("cclogger.file_io.LOCK_RETRY_BACKOFF_MS", (0, 0, 0))

        atomic_append(target, "second-bucket entry")
        next_overflow = tmp_path / "channel.log.overflow.2"
        assert next_overflow.exists()
        assert "second-bucket entry" in next_overflow.read_text(encoding="utf-8")


# ============================================================================
# Migration
# ============================================================================


class TestMigration:
    def test_no_overflow_files_drops_sentinel_returns_zero(self, tmp_path):
        n = migrate_overflow_files(tmp_path)
        assert n == 0
        assert (tmp_path / OVERFLOW_MIGRATION_SENTINEL).exists()

    def test_missing_directory_returns_zero_no_sentinel(self, tmp_path):
        ghost = tmp_path / "does-not-exist"
        n = migrate_overflow_files(ghost)
        assert n == 0
        assert not ghost.exists()

    def test_single_overflow_absorbed_with_banner(self, tmp_path):
        main = tmp_path / "channel.log"
        main.write_text("original line\n", encoding="utf-8")
        overflow = tmp_path / "channel.log.overflow.1"
        overflow.write_text("orphaned entry\n", encoding="utf-8")

        n = migrate_overflow_files(tmp_path)

        assert n == 1
        merged = main.read_text(encoding="utf-8")
        assert merged.startswith("original line\n")
        assert "═══ MIGRATED FROM OVERFLOW: 1 file(s) absorbed at" in merged
        assert "orphaned entry" in merged
        assert not overflow.exists(), "Source overflow should be deleted after migration"
        assert (tmp_path / OVERFLOW_MIGRATION_SENTINEL).exists()

    def test_multiple_overflows_absorbed_in_mtime_order(self, tmp_path):
        main = tmp_path / "channel.log"
        main.write_text("", encoding="utf-8")

        # Create three overflows; mtime ordering: o2 (oldest) < o1 < o3 (newest)
        # We deliberately number them out of order to prove sort key is mtime, not n.
        (tmp_path / "channel.log.overflow.2").write_text("OLDEST\n", encoding="utf-8")
        time.sleep(0.02)
        (tmp_path / "channel.log.overflow.1").write_text("MIDDLE\n", encoding="utf-8")
        time.sleep(0.02)
        (tmp_path / "channel.log.overflow.3").write_text("NEWEST\n", encoding="utf-8")

        n = migrate_overflow_files(tmp_path)
        assert n == 3

        merged = main.read_text(encoding="utf-8")
        # Confirm mtime ordering preserved in merged content
        oldest_pos = merged.index("OLDEST")
        middle_pos = merged.index("MIDDLE")
        newest_pos = merged.index("NEWEST")
        assert oldest_pos < middle_pos < newest_pos, (
            f"Expected mtime-ordered concatenation, got: {merged!r}"
        )

    def test_multiple_base_files_grouped_correctly(self, tmp_path):
        # Two different main files, each with their own overflow siblings
        (tmp_path / "sesslog.log").write_text("sesslog base\n", encoding="utf-8")
        (tmp_path / "shell.log").write_text("shell base\n", encoding="utf-8")
        (tmp_path / "sesslog.log.overflow.1").write_text(
            "sesslog overflow\n", encoding="utf-8"
        )
        (tmp_path / "shell.log.overflow.1").write_text(
            "shell overflow\n", encoding="utf-8"
        )

        n = migrate_overflow_files(tmp_path)
        assert n == 2

        sesslog = (tmp_path / "sesslog.log").read_text(encoding="utf-8")
        shell = (tmp_path / "shell.log").read_text(encoding="utf-8")
        assert "sesslog overflow" in sesslog
        assert "shell overflow" in shell
        # No cross-contamination
        assert "shell overflow" not in sesslog
        assert "sesslog overflow" not in shell

    def test_sentinel_prevents_second_run(self, tmp_path):
        main = tmp_path / "channel.log"
        main.write_text("base\n", encoding="utf-8")
        (tmp_path / "channel.log.overflow.1").write_text("first wave\n", encoding="utf-8")

        n1 = migrate_overflow_files(tmp_path)
        assert n1 == 1

        # Create a new overflow file AFTER the sentinel exists
        (tmp_path / "channel.log.overflow.2").write_text(
            "second wave (should NOT migrate)\n", encoding="utf-8"
        )
        n2 = migrate_overflow_files(tmp_path)
        assert n2 == 0
        # The second-wave file is still there because sentinel blocked re-scan
        assert (tmp_path / "channel.log.overflow.2").exists()
        assert "second wave" not in main.read_text(encoding="utf-8")

    def test_single_banner_per_base_even_with_many_overflows(self, tmp_path):
        main = tmp_path / "channel.log"
        main.write_text("", encoding="utf-8")
        for i in range(1, 4):
            (tmp_path / f"channel.log.overflow.{i}").write_text(
                f"entry-{i}\n", encoding="utf-8"
            )
            time.sleep(0.01)

        migrate_overflow_files(tmp_path)
        merged = main.read_text(encoding="utf-8")
        # Exactly ONE banner regardless of overflow count
        assert merged.count("═══ MIGRATED FROM OVERFLOW") == 1
        assert "3 file(s) absorbed" in merged


# ============================================================================
# EditorHeldFile — the failure mode that motivated Path 2
# ============================================================================


class TestEditorHeldFile:
    """Verify that append+lock succeeds even when an external reader holds
    the destination open — the long-lived editor-handle scenario that
    Path 1 retry alone could never solve."""

    def test_append_succeeds_while_external_reader_holds_file(self, tmp_path):
        target = tmp_path / "channel.log"
        atomic_append(target, "initial entry")

        # Simulate an editor holding the file open for reading. On Windows
        # this is the failure mode that broke the old rename primitive;
        # on POSIX it always worked. Either way, append+lock should
        # succeed because we never need DELETE access to the destination.
        with open(target, "r", encoding="utf-8") as held:
            _ = held.read()  # Establish the read; handle stays open
            atomic_append(target, "appended while held")

        contents = target.read_text(encoding="utf-8")
        assert contents == "initial entry\nappended while held\n"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
    def test_windows_share_modes_allow_concurrent_append(self, tmp_path):
        """Two distinct file handles can append cooperatively when both
        use Python's default open() sharing modes + our byte-0 lock."""
        target = tmp_path / "channel.log"
        target.write_text("", encoding="utf-8")

        with open(target, "rb") as held:  # External reader
            assert held.read() == b""
            atomic_append(target, "write under read handle")
            # External reader still valid
            held.seek(0)
            assert b"write under read handle" in held.read()
