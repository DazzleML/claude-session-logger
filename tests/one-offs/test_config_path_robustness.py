"""#52 hardening: load_config_file must never propagate an OSError.

Background
----------
`load_config_file` used to begin with `if not path.exists(): return {}`
placed OUTSIDE its `try`. That looks defensive but is the opposite:
`pathlib.Path.exists()` only swallows the errnos in
`pathlib._IGNORED_ERRNOS` (ENOENT, ENOTDIR, EBADF, ELOOP) and RE-RAISES
everything else.

On Linux an over-long filename raises ENAMETOOLONG, which is not in that
set, so the exception escaped `load_config_file` entirely and killed the
whole hook before it wrote anything -- the catastrophic half of #52
(`FATAL [Errno 36] File name too long: .../claude-history-<ctx>.json`,
zero log files for the session, hook still exits 0 so the user sees
nothing).

Why these tests force the errno instead of building a real long path
-------------------------------------------------------------------
A test that creates a genuinely over-long filename only exercises the bug
on Linux: on Windows `Path.exists()` maps the condition to an ignored
winerror and simply returns False, so the same test would silently no-op
here and give false confidence. Forcing the errno pins the CONTRACT --
"an unreadable path is treated as absent" -- on every platform.

Scope note: this is the hardening half of #52 only. It guarantees an
unreadable config path can never kill the hook. It does NOT make logging
work for over-long names -- that needs the filename-context length cap
tracked in #52 proper (and, durably, #16 FilenameBuilder).

Run: python -m pytest tests/one-offs/test_config_path_robustness.py -v
"""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

# sys.path setup happens in conftest.py
from cclogger.config import load_config_file


def _raise(exc):
    """Return a Path.exists replacement that raises `exc`."""
    def _boom(self, **kwargs):
        raise exc
    return _boom


class TestLoadConfigFileNeverPropagates:
    """An unreadable config path must degrade to {}, never raise."""

    def test_enametoolong_does_not_propagate(self, monkeypatch):
        """The #52 catastrophic mode: ENAMETOOLONG escaping the function.

        This is the exact failure reproduced on the Linux VPS and, via
        this errno-forcing form, on the Windows dev box.
        """
        monkeypatch.setattr(
            Path, "exists",
            _raise(OSError(errno.ENAMETOOLONG, "File name too long")),
            raising=False,
        )
        assert load_config_file(Path("irrelevant.json")) == {}

    @pytest.mark.parametrize(
        "err",
        [
            errno.ENAMETOOLONG,   # over-long filename (the #52 trigger)
            errno.EACCES,         # permission denied
            errno.EIO,            # I/O error
            errno.ELOOP,          # symlink loop (ignored by exists(), belt+braces)
        ],
    )
    def test_other_oserrors_do_not_propagate(self, monkeypatch, err):
        """No errno may kill the hook -- config files are optional."""
        monkeypatch.setattr(
            Path, "exists", _raise(OSError(err, "boom")), raising=False,
        )
        assert load_config_file(Path("irrelevant.json")) == {}

    def test_missing_file_still_returns_empty(self, tmp_path):
        """The ordinary absent-file case still works without the pre-check.

        `open()` inside the try raises FileNotFoundError, which the
        existing `except Exception` already handles -- which is why
        deleting the `.exists()` pre-check cost nothing.
        """
        assert load_config_file(tmp_path / "definitely-not-here.json") == {}

    def test_valid_config_still_loads(self, tmp_path):
        """Non-regression: a real config file is unaffected."""
        cfg = tmp_path / "cfg.json"
        cfg.write_text('{"display": {"verbosity": 3}}', encoding="utf-8")
        assert load_config_file(cfg) == {"display": {"verbosity": 3}}

    def test_malformed_json_returns_empty(self, tmp_path):
        """Non-regression: invalid JSON degrades rather than raising."""
        cfg = tmp_path / "bad.json"
        cfg.write_text("{not valid json", encoding="utf-8")
        assert load_config_file(cfg) == {}
