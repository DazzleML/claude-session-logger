"""Configuration loading + per-key merging + per-channel directory layout.

load_configuration honors the legacy `~/.claude/claude-history*.json` files
plus environment-variable overrides; ConfigLoader layers the v0.3.2+
plugin-settings layout on top (single-file or per-channel directory) with
the directory winning when both are present.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cclogger.config_merge import apply_override_config, parse_bool
from cclogger.debug import debug_log
from cclogger.models import Config


# ============================================================================
# Configuration Loading
# ============================================================================


def load_config_file(path: Path) -> dict[str, Any]:
    """Load a JSON config file, returning empty dict on failure."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def merge_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge two config dicts, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def load_configuration(session_context: str) -> Config:
    """Load configuration with proper precedence.

    Priority: Environment Variables > Session Config > Global Config > Defaults
    """
    home = Path.home()
    global_config_path = home / ".claude" / "claude-history.json"
    session_config_path = home / ".claude" / f"claude-history-{session_context}.json"

    # Load and merge config files
    global_config = load_config_file(global_config_path)
    session_config = load_config_file(session_config_path)
    file_config = merge_configs(global_config, session_config)

    # Start with defaults
    config = Config()

    # Apply file config
    if "verbosity" in file_config:
        try:
            v = int(file_config["verbosity"])
            if 0 <= v <= 4:
                config.verbosity = v
        except (ValueError, TypeError):
            pass

    datetime_setting = file_config.get("datetime", "full")
    if datetime_setting in ("full", "true", "1", "yes", True):
        config.datetime_mode = "full"
    elif datetime_setting == "date":
        config.datetime_mode = "date"
    elif datetime_setting in ("false", "0", "no", False, "none"):
        config.datetime_mode = "none"

    config.pwd_enabled = parse_bool(file_config.get("pwd", False))

    # Filter include list
    filter_config = file_config.get("filter", {})
    if isinstance(filter_config, dict):
        include_list = filter_config.get("include", [])
        if isinstance(include_list, list):
            config.filter_include = include_list

    # Action-only settings
    action_only_config = file_config.get("action_only", {})
    categories = action_only_config.get("categories", {})
    for cat in config.action_only.keys():
        if cat in categories:
            config.action_only[cat] = parse_bool(categories[cat])

    overrides = action_only_config.get("overrides", {})
    for tool, value in overrides.items():
        config.action_only_overrides[tool] = str(value)

    # Failure capture
    failure_config = file_config.get("failure_capture", {})
    config.failure_capture_enabled = parse_bool(failure_config.get("enabled", False))
    config.failure_capture_stderr = parse_bool(failure_config.get("capture_stderr", True))
    try:
        max_lines = int(failure_config.get("max_stderr_lines", 50))
        config.failure_capture_max_lines = max(1, min(1000, max_lines))
    except (ValueError, TypeError):
        pass

    # Environment variable overrides (highest priority)
    env_verbosity = os.environ.get("CLAUDE_HISTORY_VERBOSITY")
    if env_verbosity:
        try:
            v = int(env_verbosity)
            if 0 <= v <= 4:
                config.verbosity = v
        except ValueError:
            pass

    env_datetime = os.environ.get("CLAUDE_HISTORY_DATETIME")
    if env_datetime:
        if env_datetime in ("full", "true", "1", "yes"):
            config.datetime_mode = "full"
        elif env_datetime == "date":
            config.datetime_mode = "date"
        elif env_datetime in ("false", "0", "no", "none"):
            config.datetime_mode = "none"

    env_pwd = os.environ.get("CLAUDE_HISTORY_PWD")
    if env_pwd:
        config.pwd_enabled = parse_bool(env_pwd)

    env_filter = os.environ.get("CLAUDE_HISTORY_FILTER")
    if env_filter:
        config.filter_include = [f.strip() for f in env_filter.split(",") if f.strip()]

    # Action-only environment overrides
    for cat in config.action_only.keys():
        env_var = f"CLAUDE_HISTORY_ACTION_ONLY_{cat.upper()}"
        env_val = os.environ.get(env_var)
        if env_val:
            config.action_only[cat] = parse_bool(env_val)

    env_todowrite = os.environ.get("CLAUDE_HISTORY_ACTION_ONLY_TODOWRITE")
    if env_todowrite:
        config.action_only_overrides["TodoWrite"] = env_todowrite

    # Failure capture environment overrides
    env_failure_enabled = os.environ.get("CLAUDE_HISTORY_FAILURE_ENABLED")
    if env_failure_enabled:
        config.failure_capture_enabled = parse_bool(env_failure_enabled)

    env_failure_stderr = os.environ.get("CLAUDE_HISTORY_FAILURE_STDERR")
    if env_failure_stderr:
        config.failure_capture_stderr = parse_bool(env_failure_stderr)

    env_failure_max = os.environ.get("CLAUDE_HISTORY_FAILURE_MAX_LINES")
    if env_failure_max:
        try:
            config.failure_capture_max_lines = max(1, min(1000, int(env_failure_max)))
        except ValueError:
            pass

    return config


class ConfigLoader:
    """Load configuration from the new plugin settings location.

    Supports two config layouts (v0.3.2+, #30):
      1. **Single-file** (legacy, still supported):
         ~/.claude/plugins/settings/session-logger.json

      2. **Per-channel directory** (preferred for new installs):
         ~/.claude/plugins/settings/session-logger/
         ├── _global.json       (top-level: performance, display, action_only, ...)
         ├── channels/
         │   ├── shell.json     ({file_prefix, enabled})
         │   ├── tools.json
         │   └── ...
         └── overrides.json     (category_routes, tool_overrides)

    If the directory layout is present, it WINS over the single-file layout.
    A debug-log warning fires if both exist (the single file is ignored).
    """

    CONFIG_DIR = Path.home() / ".claude" / "plugins" / "settings"
    CONFIG_FILE = CONFIG_DIR / "session-logger.json"
    CONFIG_SUBDIR = CONFIG_DIR / "session-logger"  # Per-channel layout

    @classmethod
    def ensure_config_dir(cls) -> None:
        """Ensure the config directory exists."""
        cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, session_context: str = "") -> Config:
        """Load configuration with proper precedence.

        Priority: Environment Variables > New Config > Legacy Config > Defaults
        """
        # Start with legacy config loading for backwards compatibility
        config = load_configuration(session_context)

        # Prefer per-channel directory layout if present
        if cls.CONFIG_SUBDIR.is_dir():
            if cls.CONFIG_FILE.exists():
                debug_log(
                    f"Both layouts present: directory '{cls.CONFIG_SUBDIR}' wins; "
                    f"file '{cls.CONFIG_FILE}' ignored"
                )
            try:
                merged = cls._load_per_channel_dir(cls.CONFIG_SUBDIR)
                cls._apply_new_config(config, merged)
            except Exception as e:
                debug_log(f"Error loading per-channel config dir: {e}")
        elif cls.CONFIG_FILE.exists():
            # Fall back to single-file layout
            try:
                new_config = load_config_file(cls.CONFIG_FILE)
                cls._apply_new_config(config, new_config)
            except Exception as e:
                debug_log(f"Error loading new config: {e}")

        return config

    @classmethod
    def _load_per_channel_dir(cls, subdir: Path) -> dict[str, Any]:
        """Assemble a single config dict from the per-channel directory layout.

        Reads:
          - subdir/_global.json (top-level settings)
          - subdir/channels/*.json (one file per channel)
          - subdir/overrides.json (routing.category_routes + routing.tool_overrides)

        Returns a dict in the same shape as the single-file layout, so that
        _apply_new_config() can process it identically.
        """
        merged: dict[str, Any] = {}

        # _global.json -- top-level settings (performance/display/action_only/...)
        global_path = subdir / "_global.json"
        if global_path.exists():
            merged = load_config_file(global_path)

        # Ensure routing.channels exists for per-channel files to populate
        if "routing" not in merged:
            merged["routing"] = {}
        routing = merged["routing"]
        if "channels" not in routing:
            routing["channels"] = {}

        # channels/*.json -- one file per channel
        # v0.3.7 #45 fix: pass channel data through verbatim. The
        # apply_override protocol on ChannelConfig handles existing-channel
        # partial overrides (no file_prefix needed) and new-channel
        # declarations (file_prefix required) at apply time.
        channels_dir = subdir / "channels"
        if channels_dir.is_dir():
            for channel_file in sorted(channels_dir.glob("*.json")):
                channel_name = channel_file.stem
                channel_data = load_config_file(channel_file)
                if isinstance(channel_data, dict):
                    routing["channels"][channel_name] = channel_data

        # overrides.json -- category_routes + tool_overrides
        overrides_path = subdir / "overrides.json"
        if overrides_path.exists():
            overrides_data = load_config_file(overrides_path)
            if isinstance(overrides_data, dict):
                if "category_routes" in overrides_data:
                    routing["category_routes"] = overrides_data["category_routes"]
                if "tool_overrides" in overrides_data:
                    routing["tool_overrides"] = overrides_data["tool_overrides"]

        return merged

    @classmethod
    def _apply_new_config(cls, config: Config, data: dict[str, Any]) -> None:
        """Apply new-config-format dict to an existing Config in place.

        v0.3.7 #45 fix + Phase 6 cleanup: dispatches to the per-dataclass
        apply_override protocol in `cclogger.config_merge` (which recurses
        through RoutingConfig → ChannelConfig → ChannelOptions, plus
        PerformanceConfig). Existing channels get per-field merge that
        preserves shipped defaults the user didn't redeclare; new channels
        still require `file_prefix`.
        """
        apply_override_config(config, data)
