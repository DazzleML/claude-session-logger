"""Shared pytest fixtures for tests/one-offs/.

Adds hooks/scripts/ to sys.path so `import cclogger` resolves, and
provides cursor-isolation fixture used by several test files.
"""

from pathlib import Path
import sys

import pytest

# Make cclogger importable from any test file
_HOOKS_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "hooks" / "scripts"
if str(_HOOKS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_HOOKS_SCRIPTS))


@pytest.fixture
def isolate_cursor_state(tmp_path, monkeypatch):
    """Redirect convo cursor reads/writes to tmp_path.

    Targets the home module string form so the patch intercepts the
    lookup inside `cclogger.conversation._read_convo_cursor` /
    `_write_convo_cursor`. Patching the cclogger package namespace
    would NOT work -- those functions resolve `_convo_cursor_path`
    via their own module globals.

    Yields the directory where cursor files will be written.
    """
    cursor_dir = tmp_path / "session-states"
    cursor_dir.mkdir()
    monkeypatch.setattr(
        "cclogger.conversation._convo_cursor_path",
        lambda sid: cursor_dir / f"{sid}.convo-cursor",
    )
    return cursor_dir
