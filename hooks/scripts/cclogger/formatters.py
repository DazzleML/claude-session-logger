"""Filtering, content extraction, and entry formatting for the v0.3.x logger.

Three sections:
  - Filtering: should_log_tool / should_use_action_only consult Config.
  - Content extraction: per-tool handlers (Bash, Edit, Write, Grep, ...) build
    the rich `path:line ← snippet (-N/+ML)` strings, plus task-specific output.
  - Entry generation: format_datetime / format_tool_name / generate_entry
    weave together verbosity, action-only mode, and pwd context.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from cclogger.categorize import categorize_tool
from cclogger.config import parse_bool
from cclogger.models import (
    RESERVED_VERBOSITY_KEYS,
    ChannelOptions,
    Config,
    NewlinePolicy,
    ToolInfo,
)


# ============================================================================
# Channel-options hierarchical resolution (v0.3.7 Phase 1)
# ============================================================================
#
# 5-level precedence walk used by both _resolve_verbosity and
# _resolve_newline_policy. Most-specific match wins:
#
#   Level 1: Per-tool override                — channel_opts.<field>[tool_name]
#   Level 2: Per-sub-role match (longest prefix wins) — channel_opts.<field>[role_chain[i]]
#   Level 3: Per-role match (covered by level 2's chain walk)
#   Level 4: Channel default (string preset OR hint dict at the field root)
#   Level 5: Global default (PerformanceConfig.content_preview_length for verbosity;
#            NewlinePolicy.ESCAPE for newline_policy)
#
# Inertness during Phase 1: these helpers are defined but not yet wired
# into the per-tool handlers or SessionLogger. Phase 2+3 connects them.

# Verbosity preset names → max char count (0 = no truncation, "full" content).
# "preview" maps to None to indicate "use the global default" (level 5 fallback).
_VERBOSITY_PRESETS: dict[str, Optional[int]] = {
    "full": 0,
    "preview": None,    # None = fall through to global_default at level 5
    "name-only": -1,    # -1 = display name/role only, no content (formatter-side meaning)
}


def _role_prefix_chain(role: str) -> list[str]:
    """Walk a `:`-separated role from most-specific to least-specific.

    Examples:
      "agent"                       → ["agent"]
      "agent:user"                  → ["agent:user", "agent"]
      "agent:senior-engineer:user"  → ["agent:senior-engineer:user",
                                       "agent:senior-engineer", "agent"]
      "bash:powershell"             → ["bash:powershell", "bash"]
      ""                            → [""]

    Used by _resolve_verbosity / _resolve_newline_policy to find the most
    specific matching key in a per-role config dict. The crucial property:
    matching is per-`:`-segment, not arbitrary string prefix. So
    "agent:user" is NOT a prefix of "agent:senior-engineer:user".
    """
    if not role:
        return [""]
    parts = role.split(":")
    return [":".join(parts[: len(parts) - i]) for i in range(len(parts))]


def _is_hint_dict(value: dict) -> bool:
    """True if `value` is a verbosity-hint dict (only reserved keys), not a per-role map.

    A dict containing ONLY reserved keys (max_chars, max_lines, ...) is a
    hint dict — describes a single verbosity value. A dict containing any
    non-reserved key is treated as a per-role map.
    """
    if not value:
        return False  # empty dict — treat as no override
    return all(k in RESERVED_VERBOSITY_KEYS for k in value.keys())


def _verbosity_value_to_int(value: Any, global_default: int) -> int:
    """Coerce a single verbosity value to an int (max_chars).

    Accepts: preset string ("full", "preview", "name-only"), hint dict
    ({"max_chars": N}), or int. Falls back to `global_default` on unknowns.
    """
    if isinstance(value, str):
        preset = _VERBOSITY_PRESETS.get(value)
        if preset is None:
            return global_default  # "preview" or unknown preset → global default
        return preset  # "full" → 0; "name-only" → -1
    if isinstance(value, dict):
        if "max_chars" in value:
            return int(value["max_chars"])
        if "max_lines" in value:
            # Phase 1 stores max_lines as a separate hint; for now coerce to chars
            # via a sentinel value (negative thousands) so consumers can detect
            # and apply line-count truncation downstream. Phase 2+3 may switch
            # to a (mode, value) tuple for richer dispatch.
            return -1000 - int(value["max_lines"])  # negative sentinel; Phase 2+3 may refine
        return global_default
    if isinstance(value, int):
        return value
    return global_default


def _resolve_verbosity(
    channel_opts: ChannelOptions,
    role: str,
    tool_name: Optional[str],
    global_default: int,
) -> int:
    """Resolve the effective verbosity (max char count) for a channel + role.

    Returns 0 for "no truncation", a positive int for "truncate to N chars",
    or -1 for "display name only" (formatter-side meaning).

    See module docstring for the 5-level walk.
    """
    verbosity = channel_opts.verbosity

    # Level 5: no channel override at all → global default
    if verbosity is None:
        return global_default

    # Level 4: channel default is a string preset or hint dict (single value)
    if isinstance(verbosity, str):
        return _verbosity_value_to_int(verbosity, global_default)
    if isinstance(verbosity, dict) and _is_hint_dict(verbosity):
        return _verbosity_value_to_int(verbosity, global_default)

    # Level 1-3: per-tool override + per-role hierarchy walk
    if isinstance(verbosity, dict):
        # Level 1: per-tool override (exact tool name match)
        if tool_name and tool_name in verbosity:
            return _verbosity_value_to_int(verbosity[tool_name], global_default)
        # Level 2-3: per-role longest-prefix match
        for prefix in _role_prefix_chain(role):
            if prefix in verbosity:
                return _verbosity_value_to_int(verbosity[prefix], global_default)
        # No match in dict → global default
        return global_default

    # Unknown shape → global default
    return global_default


def _coerce_newline_policy(value: Any) -> NewlinePolicy:
    """Coerce a value to NewlinePolicy. Accepts enum, string, or unknowns (default ESCAPE)."""
    if isinstance(value, NewlinePolicy):
        return value
    if isinstance(value, str):
        try:
            return NewlinePolicy(value)
        except ValueError:
            return NewlinePolicy.ESCAPE
    return NewlinePolicy.ESCAPE


def _resolve_newline_policy(
    channel_opts: ChannelOptions,
    role: str,
    tool_name: Optional[str],
) -> NewlinePolicy:
    """Resolve the effective NewlinePolicy for a channel + role.

    Same 5-level walk as _resolve_verbosity. Defaults to NewlinePolicy.ESCAPE
    if no channel override is set (preserves current behavior).
    """
    policy = channel_opts.newline_policy

    # Level 5: no channel override → ESCAPE default
    if policy is None:
        return NewlinePolicy.ESCAPE

    # Level 4: channel default is enum or string
    if isinstance(policy, (NewlinePolicy, str)):
        return _coerce_newline_policy(policy)

    # Level 1-3: per-tool override + per-role hierarchy walk
    if isinstance(policy, dict):
        # Level 1: per-tool override
        if tool_name and tool_name in policy:
            return _coerce_newline_policy(policy[tool_name])
        # Level 2-3: per-role longest-prefix match
        for prefix in _role_prefix_chain(role):
            if prefix in policy:
                return _coerce_newline_policy(policy[prefix])
        # No match → ESCAPE default
        return NewlinePolicy.ESCAPE

    # Unknown shape → ESCAPE default
    return NewlinePolicy.ESCAPE


# ============================================================================
# Filtering Logic
# ============================================================================


def should_log_tool(tool_name: str, config: Config) -> bool:
    """Check if tool should be logged based on filtering."""
    # If no filter specified, log everything
    if not config.filter_include:
        return True

    category = categorize_tool(tool_name)
    return category in config.filter_include


def should_use_action_only(tool_name: str, config: Config) -> bool:
    """Check if tool should use action-only mode (show only tool name)."""
    # Check for specific tool override first
    if tool_name in config.action_only_overrides:
        override = config.action_only_overrides[tool_name]
        if override != "use_category":
            return parse_bool(override)

    # Use category default
    category = categorize_tool(tool_name)
    return config.action_only.get(category, False)


# ============================================================================
# Content Extraction
# ============================================================================


def get_task_content(tool_name: str, raw_json: dict[str, Any],
                     config: Optional[Config] = None) -> str:
    """Extract task-specific content for Task* tools."""
    tool_input = raw_json.get("tool_input", {})
    tool_response = raw_json.get("tool_response", {})

    # Get task description truncation limit (0 = full, no truncation)
    max_desc = 0
    if config is not None:
        max_desc = config.performance.task_description_length

    if tool_name == "TaskCreate":
        subject = tool_input.get("subject", "(no subject)")
        description = tool_input.get("description", "")

        # Extract task ID from tool_response
        task_id = ""
        if isinstance(tool_response, dict):
            task_data = tool_response.get("task", {})
            if isinstance(task_data, dict):
                task_id = task_data.get("id", "")

        id_part = f" #{task_id}" if task_id else ""

        if description:
            if max_desc > 0 and len(description) > max_desc:
                description = description[:max_desc] + "..."
            return f"CREATE{id_part}: {subject} | {description}"
        return f"CREATE{id_part}: {subject}"

    elif tool_name == "TaskUpdate":
        task_id = tool_input.get("taskId", "?")
        status = tool_input.get("status", "")
        subject = tool_input.get("subject", "")
        active_form = tool_input.get("activeForm", "")

        # Get status change info from response
        from_status = ""
        if isinstance(tool_response, dict):
            status_change = tool_response.get("statusChange", {})
            if isinstance(status_change, dict):
                from_status = status_change.get("from", "")

        output = f"UPDATE: #{task_id}"
        if status:
            if from_status:
                output += f": {from_status} -> {status}"
            else:
                output += f" -> {status}"
        if subject:
            output += f" | title='{subject}'"
        if active_form:
            output += f" | {active_form}"

        return output

    elif tool_name == "TaskList":
        return "LIST"

    elif tool_name == "TaskGet":
        task_id = tool_input.get("taskId", "?")
        return f"GET: #{task_id}"

    return tool_name


def find_line_number(
    file_path: str,
    search_string: str,
    max_file_size: Optional[int] = None,
    config: Optional[Config] = None
) -> int | None:
    """Find the starting line number of a string in a file.

    Args:
        file_path: Path to the file to search
        search_string: The string to find
        max_file_size: Skip files larger than this (overrides config)
        config: Config object to get max_file_size from

    Returns:
        Line number (1-indexed) or None if not found/error
    """
    if not search_string:
        return None

    # Determine max file size: explicit param > config > default
    if max_file_size is None:
        if config is not None:
            max_file_size = config.performance.max_file_size_for_line_search
        else:
            max_file_size = 2 * 1024 * 1024  # 2MB default

    try:
        path = Path(file_path)
        # Skip large files for performance
        if path.stat().st_size > max_file_size:
            return None
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        pos = content.find(search_string)
        if pos == -1:
            return None
        # Count newlines before position = line number (1-indexed)
        return content[:pos].count('\n') + 1
    except Exception:
        return None


def truncate_preview(
    text: str,
    max_len: Optional[int] = None,
    config: Optional[Config] = None
) -> str:
    """Create a safe, single-line preview of content.

    Args:
        text: The content to preview
        max_len: Maximum length before truncation (overrides config)
        config: Config object to get content_preview_length from

    Returns:
        A truncated, escaped preview string
    """
    if not text:
        return ""

    # Determine max length: explicit param > config > default
    if max_len is None:
        if config is not None:
            max_len = config.performance.content_preview_length
        else:
            max_len = 20  # default
    # Escape newlines for single-line display
    text = text.replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '')
    # Replace non-printable chars with ?
    text = ''.join(c if c.isprintable() or c == ' ' else '?' for c in text)
    # Truncate if needed
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def get_command_content(tool_info: ToolInfo, config: Optional[Config] = None) -> str:
    """Extract command content based on tool type."""
    tool_input = tool_info.input

    if tool_info.name in ("Bash", "PowerShell"):
        return tool_input.get("command", "")

    elif tool_info.name == "Read":
        path = tool_input.get("file_path", "")
        offset = tool_input.get("offset")  # Line number to start from
        limit = tool_input.get("limit")    # Number of lines to read

        if not path:
            return ""

        # Build path with line info for VS Code clickability
        if offset:
            # offset makes it clickable at that line
            if limit:
                # Show range: path:start-end
                end_line = offset + limit - 1
                path_display = f"{path}:{offset}-{end_line}"
            else:
                # Just starting line: path:line
                path_display = f"{path}:{offset}"
        else:
            path_display = path

        # Add line count suffix if limit specified without offset
        if limit and not offset:
            return f'"{path_display}" ({limit}L)'
        return f'"{path_display}"'

    elif tool_info.name == "Write":
        path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        preview = truncate_preview(content, config=config)
        line_count = len(content.splitlines()) if content else 0
        line_info = f" ({line_count}L)" if line_count > 0 else ""
        if path and preview:
            return f'"{path}" ← "{preview}"{line_info}'
        return f'"{path}"' if path else ""

    elif tool_info.name == "Edit":
        path = tool_input.get("file_path", "")
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        preview = truncate_preview(new_string, config=config)
        # Calculate line delta
        old_lines = len(old_string.splitlines()) if old_string else 0
        new_lines = len(new_string.splitlines()) if new_string else 0
        if old_lines == new_lines:
            line_info = f" ({new_lines}L)" if new_lines > 0 else ""
        else:
            line_info = f" (-{old_lines}/+{new_lines}L)"
        # Find line number for clickable file:line format
        line_num = find_line_number(path, new_string, config=config) if path and new_string else None
        path_with_line = f"{path}:{line_num}" if line_num else path
        if path and preview:
            return f'"{path_with_line}" ← "{preview}"{line_info}'
        return f'"{path_with_line}"' if path else ""

    elif tool_info.name == "MultiEdit":
        path = tool_input.get("file_path", "")
        return f'"{path}"' if path else ""

    elif tool_info.name == "TodoWrite":
        todos = tool_input.get("todos", [])
        return json.dumps(todos, separators=(",", ":"))

    elif tool_info.name == "LS":
        path = tool_input.get("path", "")
        return f'"{path}"' if path else ""

    elif tool_info.name == "Glob":
        pattern = tool_input.get("pattern", "")
        search_path = tool_input.get("path", "")
        if search_path:
            return f'{pattern} in "{search_path}"'
        return pattern

    elif tool_info.name == "Grep":
        pattern = tool_input.get("pattern", "")
        glob_filter = tool_input.get("glob", "")
        search_path = tool_input.get("path", "")

        result = pattern
        if glob_filter:
            result += f' | "{glob_filter}"'

        # Add path context if specified
        # Use "in" only when glob is present (to distinguish glob from path)
        # Use "|" when path only (cleaner, no ambiguity)
        if search_path:
            cwd = tool_info.raw_json.get("cwd", "")
            separator = " in " if glob_filter else " | "
            try:
                search_path_obj = Path(search_path).resolve()
                cwd_obj = Path(cwd).resolve() if cwd else None

                if search_path_obj.is_file():
                    # File - always full path for VS Code clickability
                    result += f'{separator}"{search_path_obj}"'
                elif cwd_obj and search_path_obj != cwd_obj:
                    # Directory - check if inside or outside cwd
                    try:
                        rel = search_path_obj.relative_to(cwd_obj)
                        # Inside cwd - use relative path (compact)
                        result += f'{separator}"{rel}/"'
                    except ValueError:
                        # Outside cwd - use full path
                        result += f'{separator}"{search_path_obj}"'
                # If search_path == cwd, omit (user knows where they are)
            except Exception:
                # Fallback - just show the path as given
                result += f'{separator}"{search_path}"'

        return result

    elif tool_info.name in ("WebSearch", "WebFetch"):
        return tool_input.get("url") or tool_input.get("query", "")

    elif tool_info.name in ("EnterPlanMode", "ExitPlanMode"):
        # Plan mode tools have no meaningful params - just marker
        return ""

    elif tool_info.name == "TaskOutput":
        return tool_input.get("task_id", "")

    elif tool_info.name == "TaskStop":
        return tool_input.get("task_id", "")

    elif tool_info.name in ("tool_search_tool_regex", "tool_search_tool_bm25"):
        # ToolSearch for discovering MCP tools dynamically
        return tool_input.get("query", "")

    elif tool_info.name == "Task":
        return tool_input.get("prompt", "")

    elif tool_info.name == "Skill":
        skill_name = tool_input.get("skill", "")
        skill_args = tool_input.get("args", "")
        max_args = config.performance.skill_args_length if config else 100
        if skill_args and max_args > 0:
            preview = truncate_preview(skill_args, max_len=max_args, config=config)
            return f'{skill_name} ← "{preview}"'
        return skill_name

    elif tool_info.name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        return get_task_content(tool_info.name, tool_info.raw_json, config)

    else:
        # For unknown tools, try common field names. Order matters: more
        # specific/distinctive fields first so collisions are less likely.
        # `command` covers shell-like tools (Bash/PowerShell pattern), `skill`
        # covers Skill-like, `subject` covers task-like, etc. New tools that
        # match these shapes will "just work" without needing a custom handler.
        for field in ("command", "pattern", "url", "prompt", "query", "skill", "subject", "content"):
            if field in tool_input:
                return str(tool_input[field])
        return ""


# ============================================================================
# Entry Generation
# ============================================================================


def format_datetime(mode: str, timestamp: Optional[datetime] = None) -> str:
    """Format datetime string based on mode.

    Args:
        mode: "full", "date", or "none"
        timestamp: The datetime to format. If None, uses datetime.now() (legacy fallback).
    """
    ts = timestamp or datetime.now()
    if mode == "date":
        return f"[[{ts.strftime('%Y-%m-%d')}]] "
    elif mode == "full":
        return f"[[{ts.strftime('%Y-%m-%d %H:%M:%S')}]] "
    return ""


def format_tool_name(tool_info: ToolInfo) -> str:
    """Format tool name with optional agent context prefix.

    Examples:
        - "Bash" (main session)
        - "Bash|Explore" (running inside Explore subagent)
        - "Read|Plan" (running inside Plan subagent)
    """
    if tool_info.agent_context:
        return f"{tool_info.name}|{tool_info.agent_context}"
    return tool_info.name


def generate_entry(tool_info: ToolInfo, config: Config, command_content: str,
                   event_time: datetime) -> str:
    """Generate formatted log entry based on configuration."""
    datetime_part = format_datetime(config.datetime_mode, event_time)

    pwd_part = ""
    if config.pwd_enabled:
        pwd_part = f' ["{os.getcwd()}"]'

    # Get tool name with agent context
    tool_display = format_tool_name(tool_info)

    # Prefix uncategorized tools with `?` for grep-friendly identification
    # within any channel. Pattern remains parseable: `{?ToolName: ...}`.
    if categorize_tool(tool_info.name) == "unknown":
        tool_display = f"?{tool_display}"

    # Determine content based on verbosity and action-only
    if should_use_action_only(tool_info.name, config):
        content_part = tool_display
    else:
        if config.verbosity == 0:
            content_part = command_content
        elif config.verbosity == 1:
            content_part = command_content
        elif config.verbosity == 2:
            content_part = f"{tool_display}: {command_content}"
        elif config.verbosity == 3:
            if tool_info.description:
                content_part = f"{tool_display}: {command_content} {tool_info.description}"
            else:
                content_part = f"{tool_display}: {command_content}"
        elif config.verbosity == 4:
            tool_input_json = json.dumps(tool_info.input, separators=(",", ":"))
            content_part = f"{tool_display}: {command_content} {tool_input_json}"
        else:
            content_part = f"{tool_display}: {command_content}"

    return f"{datetime_part}{{{content_part} }}{pwd_part}"
