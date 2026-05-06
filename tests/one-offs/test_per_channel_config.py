"""Tests: per-channel config file layout (v0.3.2, #30).

Validates that ConfigLoader supports both:
  1. Single-file layout (legacy): session-logger.json
  2. Per-channel directory layout: session-logger/{_global.json, channels/*.json, overrides.json}

Run: python -m pytest tests/one-offs/test_per_channel_config.py -v
"""

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks" / "scripts"))
_mod = importlib.import_module("log-command")

ConfigLoader = _mod.ConfigLoader


def _make_per_channel_layout(tmp_path: Path,
                              global_data: dict | None = None,
                              channels: dict | None = None,
                              overrides: dict | None = None) -> Path:
    """Create a per-channel config directory with the given content."""
    subdir = tmp_path / "session-logger"
    subdir.mkdir()

    if global_data:
        (subdir / "_global.json").write_text(json.dumps(global_data), encoding="utf-8")

    if channels:
        ch_dir = subdir / "channels"
        ch_dir.mkdir()
        for name, data in channels.items():
            (ch_dir / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")

    if overrides:
        (subdir / "overrides.json").write_text(json.dumps(overrides), encoding="utf-8")

    return subdir


class TestPerChannelLayoutDetection:
    """Loader detects and prefers the directory layout over single-file."""

    def test_directory_layout_is_loaded(self, tmp_path, monkeypatch):
        # Setup: per-channel layout with a custom channel
        subdir = _make_per_channel_layout(
            tmp_path,
            channels={"my_custom": {"file_prefix": ".custom_", "enabled": True}},
        )

        # Redirect ConfigLoader to use tmp paths
        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", tmp_path / "session-logger.json")
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        config = ConfigLoader.load()
        assert "my_custom" in config.routing.channels
        assert config.routing.channels["my_custom"].file_prefix == ".custom_"

    def test_directory_wins_when_both_present(self, tmp_path, monkeypatch):
        # Both layouts exist; directory should win
        single_file = tmp_path / "session-logger.json"
        single_file.write_text(json.dumps({
            "routing": {"channels": {"file_only_channel": {"file_prefix": ".fo_"}}}
        }), encoding="utf-8")

        subdir = _make_per_channel_layout(
            tmp_path,
            channels={"dir_channel": {"file_prefix": ".dc_", "enabled": True}},
        )

        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", single_file)
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        config = ConfigLoader.load()
        # Directory wins
        assert "dir_channel" in config.routing.channels
        # File ignored (no entry from it)
        assert "file_only_channel" not in config.routing.channels

    def test_falls_back_to_single_file_when_dir_absent(self, tmp_path, monkeypatch):
        # Only single-file exists
        single_file = tmp_path / "session-logger.json"
        single_file.write_text(json.dumps({
            "routing": {"channels": {"single_channel": {"file_prefix": ".sc_"}}}
        }), encoding="utf-8")

        # Subdir does NOT exist
        subdir = tmp_path / "session-logger"

        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", single_file)
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        config = ConfigLoader.load()
        assert "single_channel" in config.routing.channels


class TestPerChannelLayoutContent:
    """Each component of the per-channel layout is loaded correctly."""

    def test_global_json_loads_top_level_settings(self, tmp_path, monkeypatch):
        subdir = _make_per_channel_layout(
            tmp_path,
            global_data={
                "performance": {"content_preview_length": 50},
                "display": {"verbosity": 3},
            },
        )

        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", tmp_path / "session-logger.json")
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        config = ConfigLoader.load()
        assert config.performance.content_preview_length == 50
        assert config.verbosity == 3

    def test_overrides_json_loads_category_routes(self, tmp_path, monkeypatch):
        subdir = _make_per_channel_layout(
            tmp_path,
            overrides={
                "category_routes": {
                    "bash": ["shell"],  # custom route
                }
            },
        )

        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", tmp_path / "session-logger.json")
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        config = ConfigLoader.load()
        assert config.routing.category_routes["bash"] == ["shell"]

    def test_overrides_json_loads_tool_overrides(self, tmp_path, monkeypatch):
        subdir = _make_per_channel_layout(
            tmp_path,
            overrides={
                "tool_overrides": {
                    "MyTool": ["sesslog"],
                }
            },
        )

        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", tmp_path / "session-logger.json")
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        config = ConfigLoader.load()
        assert config.routing.tool_overrides["MyTool"] == ["sesslog"]

    def test_default_channels_still_present_when_using_dir_layout(self, tmp_path, monkeypatch):
        # User adds a custom channel via dir layout; default channels should still merge in
        subdir = _make_per_channel_layout(
            tmp_path,
            channels={"my_extra": {"file_prefix": ".extra_", "enabled": True}},
        )

        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", tmp_path / "session-logger.json")
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        config = ConfigLoader.load()
        # Custom channel from dir layout
        assert "my_extra" in config.routing.channels
        # Default channels still present (per-key merge)
        assert "shell" in config.routing.channels
        assert "tools" in config.routing.channels  # added in v0.3.0


class TestPerChannelLayoutRobustness:
    """Robustness: malformed/missing pieces don't break loading."""

    def test_empty_subdir_falls_through_to_defaults(self, tmp_path, monkeypatch):
        # Subdir exists but is completely empty
        subdir = tmp_path / "session-logger"
        subdir.mkdir()

        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", tmp_path / "session-logger.json")
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        config = ConfigLoader.load()
        # Should not crash; defaults still present
        assert "shell" in config.routing.channels
        assert "tools" in config.routing.channels

    def test_channel_file_without_file_prefix_is_skipped(self, tmp_path, monkeypatch):
        subdir = _make_per_channel_layout(
            tmp_path,
            channels={"bad_channel": {"enabled": True}},  # missing file_prefix
        )

        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", tmp_path / "session-logger.json")
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        config = ConfigLoader.load()
        # bad_channel without file_prefix should not be added
        assert "bad_channel" not in config.routing.channels

    def test_malformed_overrides_json_is_silent(self, tmp_path, monkeypatch):
        subdir = tmp_path / "session-logger"
        subdir.mkdir()
        (subdir / "overrides.json").write_text("{not valid json", encoding="utf-8")

        monkeypatch.setattr(ConfigLoader, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(ConfigLoader, "CONFIG_FILE", tmp_path / "session-logger.json")
        monkeypatch.setattr(ConfigLoader, "CONFIG_SUBDIR", subdir)

        # Should not raise
        config = ConfigLoader.load()
        # Defaults still loaded
        assert "shell" in config.routing.channels
