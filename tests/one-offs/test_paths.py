"""Tests: cclogger.paths -- Claude-dir resolution + relocation.

Validates the single base-dir resolver that replaced ~20 hard-coded
`Path.home() / ".claude"` sites, and the relocation precedence shared with
csb: CLAUDE_DIR > CLAUDE_CONFIG_DIR > ~/.claude.

Run: python -m pytest tests/one-offs/test_paths.py -v
"""

from pathlib import Path

from cclogger import paths


def _clear_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)


# ---- claude_dir() precedence ------------------------------------------------


def test_default_is_home_dotclaude(monkeypatch):
    _clear_env(monkeypatch)
    assert paths.claude_dir() == Path.home() / ".claude"


def test_claude_config_dir_relocates(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "moved"))
    assert paths.claude_dir() == tmp_path / "moved"


def test_claude_dir_beats_config_dir(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CLAUDE_DIR", str(tmp_path / "own"))
    assert paths.claude_dir() == tmp_path / "own"


def test_env_value_expanduser(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "~/relocated-claude")
    assert paths.claude_dir() == Path.home() / "relocated-claude"


# ---- accessor composition ---------------------------------------------------


def test_accessors_compose_under_claude_dir(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    base = tmp_path / "data" / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(base))
    assert paths.session_states() == base / "session-states"
    assert paths.sesslogs() == base / "sesslogs"
    assert paths.logs() == base / "logs"
    assert paths.captures() == base / "captures"
    assert paths.plugins_settings() == base / "plugins" / "settings"
    assert paths.global_config() == base / "claude-history.json"
    assert paths.session_config("abcd") == base / "claude-history-abcd.json"


def test_accessors_track_default(monkeypatch):
    _clear_env(monkeypatch)
    home_claude = Path.home() / ".claude"
    assert paths.sesslogs() == home_claude / "sesslogs"
    assert paths.session_states() == home_claude / "session-states"


# ---- relocation end-to-end (the container scenario) -------------------------


def test_relocation_keeps_logger_data_with_relocated_claude(monkeypatch, tmp_path):
    """A relocated CLAUDE_CONFIG_DIR (containers/host-mounts) routes ALL the
    logger's writeable trees under the relocated dir -- not split to ~/.claude
    -- so csb (which follows the same precedence) finds them."""
    _clear_env(monkeypatch)
    relocated = tmp_path / "srv" / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(relocated))
    for accessor in (paths.session_states, paths.sesslogs, paths.logs,
                     paths.captures, paths.plugins_settings):
        assert str(accessor()).startswith(str(relocated)), accessor.__name__
