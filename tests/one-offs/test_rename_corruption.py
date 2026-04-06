"""One-off test: Verify _rename_files_for_session_change doesn't corrupt filenames.

Validates the fix for #17 (blind str.replace corruption) and the
directory truncation fix (sanitize_dirname 50-char limit).

Run: python -m pytest tests/one-offs/test_rename_corruption.py -v
"""

import importlib
import re
import sys
import tempfile
from pathlib import Path

# log-command.py has a hyphen so we need importlib
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks" / "scripts"))
_mod = importlib.import_module("log-command")

_rename_files_for_session_change = _mod._rename_files_for_session_change
sanitize_dirname = _mod.sanitize_dirname
build_session_directory = _mod.build_session_directory


GUID = "7b59e24c-26ee-42d8-9ea3-0ccadda35c0e"
USERNAME = "testuser"


class TestRenameFilesForSessionChange:
    """Tests for _rename_files_for_session_change (#17 fix)."""

    def _make_sesslog_dir(self, tmp_path, old_name, files):
        """Create a temp session directory with given files."""
        d = tmp_path / f"{old_name}__{GUID}_{USERNAME}"
        d.mkdir()
        for fname in files:
            (d / fname).write_text("test content")
        return d

    def test_skip_transcript_jsonl(self, tmp_path):
        """transcript.jsonl must NOT be renamed (#17 core bug)."""
        d = self._make_sesslog_dir(tmp_path, "c", [
            "transcript.jsonl",
            f".sesslog_bash__c__{GUID}_{USERNAME}.log",
        ])
        _rename_files_for_session_change(d, "c", "NEWNAME", GUID)
        assert (d / "transcript.jsonl").exists(), "transcript.jsonl was corrupted"

    def test_skip_non_log_files(self, tmp_path):
        """Arbitrary files in the directory must not be touched."""
        d = self._make_sesslog_dir(tmp_path, "dev", [
            "notes.txt",
            "developer-guide.md",
            f".sesslog_bash__dev__{GUID}_{USERNAME}.log",
        ])
        _rename_files_for_session_change(d, "dev", "NEWNAME", GUID)
        assert (d / "notes.txt").exists(), "notes.txt was renamed"
        assert (d / "developer-guide.md").exists(), "developer-guide.md was renamed"

    def test_rename_sesslog_file(self, tmp_path):
        """Log files with session name in structural position should be renamed."""
        old_name = "my-session"
        new_name = "renamed-session"
        fname = f".sesslog_bash__{old_name}__{GUID}_{USERNAME}.log"
        d = self._make_sesslog_dir(tmp_path, old_name, [fname])

        _rename_files_for_session_change(d, old_name, new_name, GUID)

        expected = f".sesslog_bash__{new_name}__{GUID}_{USERNAME}.log"
        assert (d / expected).exists(), f"Expected {expected} not found"
        assert not (d / fname).exists(), f"Old file {fname} still exists"

    def test_rename_shell_file(self, tmp_path):
        """Shell log files should also be renamed."""
        old_name = "my-session"
        new_name = "renamed-session"
        fname = f".shell_bash__{old_name}__{GUID}_{USERNAME}.log"
        d = self._make_sesslog_dir(tmp_path, old_name, [fname])

        _rename_files_for_session_change(d, old_name, new_name, GUID)

        expected = f".shell_bash__{new_name}__{GUID}_{USERNAME}.log"
        assert (d / expected).exists()

    def test_rename_tasks_file(self, tmp_path):
        """Task log files should also be renamed."""
        old_name = "my-session"
        new_name = "renamed-session"
        fname = f".tasks_bash__{old_name}__{GUID}_{USERNAME}.log"
        d = self._make_sesslog_dir(tmp_path, old_name, [fname])

        _rename_files_for_session_change(d, old_name, new_name, GUID)

        expected = f".tasks_bash__{new_name}__{GUID}_{USERNAME}.log"
        assert (d / expected).exists()

    def test_short_name_no_corruption(self, tmp_path):
        """Short session name 'c' must not corrupt 'transcript' or '.sesslog'."""
        fname_log = f".sesslog_bash__c__{GUID}_{USERNAME}.log"
        fname_shell = f".shell_bash__c__{GUID}_{USERNAME}.log"
        d = self._make_sesslog_dir(tmp_path, "c", [
            "transcript.jsonl",
            fname_log,
            fname_shell,
        ])

        _rename_files_for_session_change(d, "c", "LONG-NEW-NAME", GUID)

        # transcript must be untouched
        assert (d / "transcript.jsonl").exists(), "transcript.jsonl corrupted by 'c' replacement"
        # log files should be renamed correctly
        assert (d / f".sesslog_bash__LONG-NEW-NAME__{GUID}_{USERNAME}.log").exists()
        assert (d / f".shell_bash__LONG-NEW-NAME__{GUID}_{USERNAME}.log").exists()

    def test_name_substring_of_prefix(self, tmp_path):
        """Session name 'log' must not corrupt '.sesslog_' prefix."""
        fname = f".sesslog_bash__log__{GUID}_{USERNAME}.log"
        d = self._make_sesslog_dir(tmp_path, "log", [fname])

        _rename_files_for_session_change(d, "log", "NEWNAME", GUID)

        expected = f".sesslog_bash__NEWNAME__{GUID}_{USERNAME}.log"
        assert (d / expected).exists(), f"Expected {expected}"
        # Verify .sesslog_ prefix wasn't corrupted
        files = [f.name for f in d.iterdir() if f.is_file()]
        for f in files:
            if f.startswith(".sess"):
                assert f.startswith(".sesslog_"), f"Prefix corrupted: {f}"


class TestSanitizeDirname:
    """Tests for sanitize_dirname truncation fix."""

    def test_no_truncation_at_50(self):
        """Names under 200 chars should not be truncated (was 50 before fix)."""
        name = "A" * 100
        assert len(sanitize_dirname(name)) == 100

    def test_old_limit_would_truncate(self):
        """52-char name that was truncated by the old 50-char limit."""
        name = "CLAUDE-SESSION-LOGGER__testing-new-js-installer-pt2"
        assert len(name) == 51  # Was truncated at 50 by old limit
        result = sanitize_dirname(name)
        assert result == name, f"Truncated to: {result}"

    def test_respects_explicit_max_len(self):
        """Explicit max_len should be honored."""
        name = "A" * 100
        assert len(sanitize_dirname(name, max_len=30)) == 30

    def test_strips_unsafe_chars(self):
        """Filesystem-unsafe characters should be replaced."""
        assert sanitize_dirname('foo<bar>baz') == 'foo_bar_baz'
        assert sanitize_dirname('a:b/c\\d') == 'a_b_c_d'


class TestBuildSessionDirectory:
    """Tests for build_session_directory dynamic budget."""

    def test_long_name_not_truncated(self):
        """Session names up to ~215 chars should fit within 255 limit."""
        long_name = "A" * 200
        result = build_session_directory(long_name, GUID, USERNAME)
        # Should contain the full name
        assert long_name in result

    def test_extremely_long_name_truncated(self):
        """Names exceeding filesystem budget should be truncated."""
        extreme_name = "A" * 300
        result = build_session_directory(extreme_name, GUID, USERNAME)
        assert len(result) <= 255

    def test_unnamed_session(self):
        """Unnamed sessions should produce __{guid}_{user} format."""
        result = build_session_directory(None, GUID, USERNAME)
        assert result == f"__{GUID}_{USERNAME}"

    def test_named_session_format(self):
        """Named sessions should produce {name}__{guid}_{user} format."""
        result = build_session_directory("my-session", GUID, USERNAME)
        assert result == f"my-session__{GUID}_{USERNAME}"
