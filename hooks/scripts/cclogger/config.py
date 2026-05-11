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

from cclogger.debug import debug_log
from cclogger.models import (
    RESERVED_VERBOSITY_KEYS,
    ChannelConfig,
    ChannelOptions,
    Config,
)


# ============================================================================
# Channel-options validation helpers (v0.3.7 Phase 1)
# ============================================================================


def _validate_verbosity_dict(verbosity: dict, channel_name: str) -> dict:
    """Inspect a verbosity dict; reject role-name collisions with reserved keys.

    Returns the dict (possibly with bogus role-keys filtered out + debug_log warnings).
    Pure hint dicts (only reserved keys) pass through unchanged.

    Behavior:
      - Pure hint dict ({"max_chars": N})            → returned as-is
      - Pure per-role map ({"agent:user": "preview"}) → returned as-is
      - Mixed (some reserved + some non-reserved keys, e.g.,
        {"max_chars": "preview", "user": "full"})    → reserved keys logged + dropped;
                                                       remaining keys returned as per-role map
    """
    if not isinstance(verbosity, dict) or not verbosity:
        return verbosity
    reserved_in_dict = {k for k in verbosity if k in RESERVED_VERBOSITY_KEYS}
    non_reserved = {k for k in verbosity if k not in RESERVED_VERBOSITY_KEYS}
    # Pure hint dict (all keys are reserved) → keep
    if reserved_in_dict and not non_reserved:
        return verbosity
    # Pure role map (no reserved keys) → keep
    if non_reserved and not reserved_in_dict:
        return verbosity
    # Mixed → ambiguous. Drop the reserved keys (they can't be roles) and
    # log a warning. The remaining is treated as a per-role map.
    debug_log(
        f"channel '{channel_name}': verbosity dict mixes reserved keys "
        f"({sorted(reserved_in_dict)}) with role keys ({sorted(non_reserved)}). "
        f"Reserved keys cannot be role names — dropping them. "
        f"Use a pure hint dict OR pure role map; not both."
    )
    return {k: v for k, v in verbosity.items() if k not in RESERVED_VERBOSITY_KEYS}


def _build_channel_options(opts_data: Any, channel_name: str) -> ChannelOptions:
    """Construct a ChannelOptions from a JSON dict (or None)."""
    if not isinstance(opts_data, dict):
        return ChannelOptions()
    kwargs: dict[str, Any] = {}
    if "verbosity" in opts_data:
        v = opts_data["verbosity"]
        if isinstance(v, dict):
            v = _validate_verbosity_dict(v, channel_name)
        kwargs["verbosity"] = v
    if "formatter" in opts_data and isinstance(opts_data["formatter"], str):
        kwargs["formatter"] = opts_data["formatter"]
    if "newline_policy" in opts_data:
        # Stored as-is (string or dict); resolved at format time via _coerce_newline_policy.
        # Per-role dicts also validated for reserved-key collisions.
        np = opts_data["newline_policy"]
        if isinstance(np, dict):
            np = _validate_verbosity_dict(np, channel_name)
        kwargs["newline_policy"] = np
    if "role_labels" in opts_data and isinstance(opts_data["role_labels"], dict):
        kwargs["role_labels"] = {
            str(k): str(v) for k, v in opts_data["role_labels"].items()
        }
    if "suppress_markers" in opts_data:
        kwargs["suppress_markers"] = bool(opts_data["suppress_markers"])
    return ChannelOptions(**kwargs)


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


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse a value as boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if isinstance(value, int):
        return value != 0
    return default


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
        channels_dir = subdir / "channels"
        if channels_dir.is_dir():
            for channel_file in sorted(channels_dir.glob("*.json")):
                channel_name = channel_file.stem
                channel_data = load_config_file(channel_file)
                if isinstance(channel_data, dict) and "file_prefix" in channel_data:
                    channel_dict = {
                        "file_prefix": channel_data["file_prefix"],
                        "enabled": channel_data.get("enabled", True),
                    }
                    # v0.3.7: pass options through verbatim; _apply_new_config
                    # constructs the ChannelOptions instance with validation.
                    if "options" in channel_data:
                        channel_dict["options"] = channel_data["options"]
                    routing["channels"][channel_name] = channel_dict

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
        """Apply new config format settings."""
        # Performance settings
        perf = data.get("performance", {})
        if isinstance(perf, dict):
            if "max_file_size_for_line_search" in perf:
                try:
                    config.performance.max_file_size_for_line_search = int(
                        perf["max_file_size_for_line_search"]
                    )
                except (ValueError, TypeError):
                    pass
            if "content_preview_length" in perf:
                try:
                    val = int(perf["content_preview_length"])
                    config.performance.content_preview_length = max(0, min(200, val))
                except (ValueError, TypeError):
                    pass
            if "task_description_length" in perf:
                try:
                    val = int(perf["task_description_length"])
                    config.performance.task_description_length = max(0, val)
                except (ValueError, TypeError):
                    pass
            if "skill_args_length" in perf:
                try:
                    val = int(perf["skill_args_length"])
                    config.performance.skill_args_length = max(0, val)
                except (ValueError, TypeError):
                    pass

        # Display settings (override legacy)
        display = data.get("display", {})
        if isinstance(display, dict):
            if "verbosity" in display:
                try:
                    v = int(display["verbosity"])
                    if 0 <= v <= 4:
                        config.verbosity = v
                except (ValueError, TypeError):
                    pass
            if "datetime" in display:
                dt = display["datetime"]
                if dt in ("full", "date", "none"):
                    config.datetime_mode = dt
            if "pwd" in display:
                config.pwd_enabled = parse_bool(display["pwd"])

        # Routing settings
        routing = data.get("routing", {})
        if isinstance(routing, dict):
            # Channels
            channels = routing.get("channels", {})
            if isinstance(channels, dict):
                for name, channel_data in channels.items():
                    if isinstance(channel_data, dict) and "file_prefix" in channel_data:
                        # v0.3.7: build ChannelOptions if `options` present;
                        # otherwise default ChannelOptions() preserves Phase 0 behavior.
                        opts = _build_channel_options(
                            channel_data.get("options"), name
                        )
                        config.routing.channels[name] = ChannelConfig(
                            file_prefix=channel_data["file_prefix"],
                            enabled=channel_data.get("enabled", True),
                            options=opts,
                        )

            # Category routes
            cat_routes = routing.get("category_routes", {})
            if isinstance(cat_routes, dict):
                for category, channels_list in cat_routes.items():
                    if isinstance(channels_list, list):
                        config.routing.category_routes[category] = channels_list

            # Tool overrides
            tool_overrides = routing.get("tool_overrides", {})
            if isinstance(tool_overrides, dict):
                for tool_name, channels_list in tool_overrides.items():
                    if isinstance(channels_list, list):
                        config.routing.tool_overrides[tool_name] = channels_list

            # Subtype routing (v0.3.3, #31): per-category opt-in for splitting
            # entries into per-subtype channels. Accepts bool or list of subtypes.
            subtype_routing = routing.get("subtype_routing", {})
            if isinstance(subtype_routing, dict):
                for category, value in subtype_routing.items():
                    if isinstance(value, (bool, list)):
                        config.routing.subtype_routing[category] = value

        # Action-only settings (override legacy)
        action_only = data.get("action_only", {})
        if isinstance(action_only, dict):
            categories = action_only.get("categories", {})
            if isinstance(categories, dict):
                for cat, val in categories.items():
                    config.action_only[cat] = parse_bool(val)
            overrides = action_only.get("overrides", {})
            if isinstance(overrides, dict):
                for tool, val in overrides.items():
                    config.action_only_overrides[tool] = str(val)

        # Failure capture settings (override legacy)
        failure = data.get("failure_capture", {})
        if isinstance(failure, dict):
            if "enabled" in failure:
                config.failure_capture_enabled = parse_bool(failure["enabled"])
            if "capture_stderr" in failure:
                config.failure_capture_stderr = parse_bool(failure["capture_stderr"])
            if "max_stderr_lines" in failure:
                try:
                    val = int(failure["max_stderr_lines"])
                    config.failure_capture_max_lines = max(1, min(1000, val))
                except (ValueError, TypeError):
                    pass
