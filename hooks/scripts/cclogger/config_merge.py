"""Per-key merge protocol for typed config dataclasses.

This module owns the apply_override functions that merge a partial user
override dict into an existing typed Config (or any nested typed
dataclass). The dataclasses themselves stay as pure data definitions in
`cclogger/models.py` — they have no methods. The merge mechanism is the
single thing that would change if we ever swap the implementation
(e.g. wholesale to OmegaConf), so keeping it isolated keeps the swap
surface a single file.

Design (v0.3.7-pre Phase 6, GitHub #45):
  - Each typed dataclass has a corresponding apply_override_* function.
  - Each function walks fields explicitly present in the override dict;
    keys absent from override preserve the current value, keys present
    override (with coercion).
  - Nested dataclasses recurse via their own apply_override_* function.
  - Each function owns its own coercion (string→enum for NewlinePolicy,
    dict validation for verbosity, etc.).
  - For new channels (not present in defaults), `file_prefix` remains
    required — it is the sentinel that distinguishes "declare new
    channel" from "override existing channel". apply_override_routing_config
    enforces this with a debug_log warning when missing.

Replaces v0.3.6 whole-record reconstruction in
ConfigLoader._apply_new_config that silently dropped shipped channel
defaults whenever a user provided any partial override (Bug #45).

The two coercion helpers `parse_bool` and `_validate_per_role_dict`
also live here (moved from models.py / config.py) since they exist
solely to support the merge protocol.
"""

from __future__ import annotations

from typing import Any

from cclogger.debug import debug_log
from cclogger.models import (
    HINT_VERBOSITY_KEYS,
    ChannelConfig,
    ChannelOptions,
    Config,
    NewlinePolicy,
    PerformanceConfig,
    RoutingConfig,
)


# ============================================================================
# Coercion helpers
# ============================================================================


def parse_bool(value: Any, default: bool = False) -> bool:
    """Coerce a JSON value (bool/str/int) to bool. Used across config layers."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if isinstance(value, int):
        return value != 0
    return default


def _validate_per_role_dict(value: dict, channel_name: str, field_name: str = "verbosity") -> dict:
    """Inspect a per-role dict; reject hint/role-key ambiguity.

    Used for both `verbosity` and `newline_policy` dicts. Returns the dict
    (possibly with bogus hint keys filtered out + debug_log warning).

    `field_name` is used only in the debug_log message so users see which
    field they misconfigured.

    Behavior:
      - Pure hint dict ({"max_chars": N})                  → returned as-is
      - Pure per-role map ({"agent:user": "preview"})      → returned as-is
      - Per-role map with _default ({"_default": "full",
        "write": {"max_chars": 20}})                       → returned as-is
      - Mixed hint+role ({"max_chars": 50, "user": "full"}) → hint keys
                                                              dropped + logged
    """
    if not isinstance(value, dict) or not value:
        return value
    hint_in_dict = {k for k in value if k in HINT_VERBOSITY_KEYS}
    non_hint = {k for k in value if k not in HINT_VERBOSITY_KEYS}
    if hint_in_dict and not non_hint:
        return value
    if non_hint and not hint_in_dict:
        return value
    debug_log(
        f"channel '{channel_name}': {field_name} dict mixes hint keys "
        f"({sorted(hint_in_dict)}) with role/_default keys ({sorted(non_hint)}). "
        f"Hint keys (max_chars/max_lines) cannot coexist with role keys — "
        f"dropping them. Use a pure hint dict OR a per-role map (with optional "
        f"_default fallback)."
    )
    return {k: v for k, v in value.items() if k not in HINT_VERBOSITY_KEYS}


# ============================================================================
# apply_override functions — one per typed dataclass
# ============================================================================


def apply_override_channel_options(
    target: ChannelOptions, override: Any, channel_name: str = ""
) -> None:
    """Apply a partial override dict to an existing ChannelOptions in place.

    Per-field merge: keys absent from override preserve current value;
    keys present override the value (with coercion).
    """
    if not isinstance(override, dict):
        return

    if "verbosity" in override:
        v = override["verbosity"]
        if isinstance(v, dict):
            target.verbosity = _validate_per_role_dict(v, channel_name, "verbosity")
        elif v is None or isinstance(v, str):
            target.verbosity = v

    if "formatter" in override and isinstance(override["formatter"], str):
        target.formatter = override["formatter"]

    if "newline_policy" in override:
        v = override["newline_policy"]
        if isinstance(v, dict):
            target.newline_policy = _validate_per_role_dict(v, channel_name, "newline_policy")
        elif v is None or isinstance(v, (str, NewlinePolicy)):
            target.newline_policy = v

    if "role_labels" in override:
        v = override["role_labels"]
        if isinstance(v, dict):
            target.role_labels = {str(k): str(val) for k, val in v.items()}
        elif v is None:
            target.role_labels = None

    if "suppress_markers" in override:
        target.suppress_markers = parse_bool(override["suppress_markers"])

    if "subtype_split" in override:
        v = override["subtype_split"]
        if isinstance(v, bool):
            target.subtype_split = v
        elif isinstance(v, list):
            # Filter to strings; non-string entries dropped silently
            target.subtype_split = [item for item in v if isinstance(item, str)]
        elif v is None:
            target.subtype_split = False


def apply_override_channel_config(
    target: ChannelConfig, override: Any, channel_name: str = ""
) -> None:
    """Apply partial override dict to existing ChannelConfig in place.

    Per-field merge across file_prefix/enabled, recurses into options.
    """
    if not isinstance(override, dict):
        return

    if "file_prefix" in override and isinstance(override["file_prefix"], str):
        target.file_prefix = override["file_prefix"]

    if "enabled" in override:
        target.enabled = parse_bool(override["enabled"], default=True)

    if "options" in override:
        v = override["options"]
        if isinstance(v, dict):
            apply_override_channel_options(target.options, v, channel_name)
        elif v is None:
            target.options = ChannelOptions()


def apply_override_routing_config(target: RoutingConfig, override: Any) -> None:
    """Apply partial override dict to existing RoutingConfig in place.

    For `channels`: existing entries get per-field merge via
    apply_override_channel_config (preserves shipped defaults — Bug #45 fix).
    New entries must declare `file_prefix` or are skipped with a debug_log
    warning. For `category_routes`/`tool_overrides`/`subtype_routing`:
    per-key replace (lists/bools are atomic values).
    """
    if not isinstance(override, dict):
        return

    channels = override.get("channels")
    if isinstance(channels, dict):
        for name, channel_data in channels.items():
            if not isinstance(channel_data, dict):
                continue
            if name in target.channels:
                apply_override_channel_config(target.channels[name], channel_data, name)
            else:
                fp = channel_data.get("file_prefix")
                if not isinstance(fp, str):
                    debug_log(
                        f"new channel '{name}' missing required 'file_prefix' "
                        f"string; skipping"
                    )
                    continue
                new_channel = ChannelConfig(file_prefix=fp)
                apply_override_channel_config(new_channel, channel_data, name)
                target.channels[name] = new_channel

    cat_routes = override.get("category_routes")
    if isinstance(cat_routes, dict):
        for category, channels_list in cat_routes.items():
            if isinstance(channels_list, list):
                target.category_routes[category] = channels_list

    tool_overrides = override.get("tool_overrides")
    if isinstance(tool_overrides, dict):
        for tool_name, channels_list in tool_overrides.items():
            if isinstance(channels_list, list):
                target.tool_overrides[tool_name] = channels_list

    # v0.3.7-pre (#87): mcp_server_routes is a dict[str, list[str]] keyed by
    # MCP server name. Per-key replace (atomic value semantics, same as
    # tool_overrides). Users can extend or override the default `todoai`
    # mapping or add new ones; setting an empty list clears the server's
    # additional routing.
    mcp_routes = override.get("mcp_server_routes")
    if isinstance(mcp_routes, dict):
        for server_name, channels_list in mcp_routes.items():
            if isinstance(channels_list, list):
                target.mcp_server_routes[server_name] = channels_list

    # NOTE: v0.3.3 `subtype_routing` is removed in v0.3.7-pre (supersedes #48).
    # Subtype splitting is now per-channel via ChannelOptions.subtype_split.
    # Any `routing.subtype_routing` key in user config is silently ignored.


def apply_override_performance_config(target: PerformanceConfig, override: Any) -> None:
    """Apply partial override dict to existing PerformanceConfig in place."""
    if not isinstance(override, dict):
        return

    if "max_file_size_for_line_search" in override:
        try:
            target.max_file_size_for_line_search = int(
                override["max_file_size_for_line_search"]
            )
        except (ValueError, TypeError):
            pass

    if "content_preview_length" in override:
        try:
            val = int(override["content_preview_length"])
            target.content_preview_length = max(0, min(200, val))
        except (ValueError, TypeError):
            pass

    if "task_description_length" in override:
        try:
            val = int(override["task_description_length"])
            target.task_description_length = max(0, val)
        except (ValueError, TypeError):
            pass

    if "skill_args_length" in override:
        try:
            val = int(override["skill_args_length"])
            target.skill_args_length = max(0, val)
        except (ValueError, TypeError):
            pass


def apply_override_config(target: Config, override: Any) -> None:
    """Apply partial override dict to existing Config in place.

    Walks every nested typed structure via its own apply_override_* function.
    Fields absent from override preserve their existing values — the bug fix
    that makes shipped channel/option defaults survive partial user
    overrides (#45).
    """
    if not isinstance(override, dict):
        return

    if "performance" in override:
        v = override["performance"]
        if isinstance(v, dict):
            apply_override_performance_config(target.performance, v)
        elif v is None:
            target.performance = PerformanceConfig()

    # Display settings (top-level fields on Config, nested under "display" in JSON)
    display = override.get("display")
    if isinstance(display, dict):
        if "verbosity" in display:
            try:
                v_int = int(display["verbosity"])
                if 0 <= v_int <= 4:
                    target.verbosity = v_int
            except (ValueError, TypeError):
                pass
        if "datetime" in display:
            dt = display["datetime"]
            if dt in ("full", "date", "none"):
                target.datetime_mode = dt
        if "pwd" in display:
            target.pwd_enabled = parse_bool(display["pwd"])

    if "routing" in override:
        v = override["routing"]
        if isinstance(v, dict):
            apply_override_routing_config(target.routing, v)
        elif v is None:
            target.routing = RoutingConfig()

    action_only = override.get("action_only")
    if isinstance(action_only, dict):
        categories = action_only.get("categories")
        if isinstance(categories, dict):
            for cat, val in categories.items():
                target.action_only[cat] = parse_bool(val)
        overrides_dict = action_only.get("overrides")
        if isinstance(overrides_dict, dict):
            for tool, val in overrides_dict.items():
                target.action_only_overrides[tool] = str(val)

    failure = override.get("failure_capture")
    if isinstance(failure, dict):
        if "enabled" in failure:
            target.failure_capture_enabled = parse_bool(failure["enabled"])
        if "capture_stderr" in failure:
            target.failure_capture_stderr = parse_bool(failure["capture_stderr"])
        if "max_stderr_lines" in failure:
            try:
                v_int = int(failure["max_stderr_lines"])
                target.failure_capture_max_lines = max(1, min(1000, v_int))
            except (ValueError, TypeError):
                pass
