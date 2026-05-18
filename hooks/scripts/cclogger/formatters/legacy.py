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
from cclogger.config_merge import parse_bool
from cclogger.models import (
    HINT_VERBOSITY_KEYS,
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
    """True if `value` is a verbosity-hint dict (only HINT keys), not a per-role map.

    A dict containing ONLY hint keys (max_chars, max_lines) is a hint dict —
    describes a single verbosity value. A dict containing any other key
    (including the per-role-reserved `_default` or any role name) is treated
    as a per-role map.

    Phase 2+3: split from the broader RESERVED_VERBOSITY_KEYS set so the new
    `_default` reserved key (used for per-role-dict fallback) doesn't make a
    dict look like a hint dict. A dict like {"_default": "full", "write": ...}
    is per-role with a fallback, not a hint.
    """
    if not value:
        return False  # empty dict — treat as no override
    return all(k in HINT_VERBOSITY_KEYS for k in value.keys())


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
        # Level 4 (Phase 2+3 extension): `_default` key inside a per-role dict
        # acts as the channel-level fallback. Lets a channel express
        # "full for everything, except these tools at N chars" — needed for
        # sesslog to truncate Write/Edit while keeping prose full.
        if "_default" in verbosity:
            return _verbosity_value_to_int(verbosity["_default"], global_default)
        # No match in dict + no _default → global default
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
        # Level 4 (Phase 2+3 extension): `_default` key as channel-level fallback
        if "_default" in policy:
            return _coerce_newline_policy(policy["_default"])
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

    elif tool_name == "TodoWrite":
        # #87: TodoWrite routed to tasks channel. Summarize the todo list
        # with item counts by status and a preview of the first item.
        todos = tool_input.get("todos", [])
        if not isinstance(todos, list) or not todos:
            return "TODOS: (empty)"
        n = len(todos)
        pending = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "pending")
        in_progress = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "in_progress")
        completed = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
        first = todos[0] if isinstance(todos[0], dict) else {}
        first_subj = first.get("content") or first.get("subject") or ""
        if max_desc > 0 and len(first_subj) > max_desc:
            first_subj = first_subj[:max_desc] + "..."
        breakdown = f"{n} item(s) [{pending}p/{in_progress}ip/{completed}c]"
        if first_subj:
            return f"TODOS: {breakdown} first: {first_subj}"
        return f"TODOS: {breakdown}"

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
    """Extract command content based on tool type.

    Phase 2+3 Step 7: thin wrapper over get_command_content_structured() that
    returns just the legacy_string field. New callers should use the
    structured form directly to access raw_content + summary_template for
    per-channel snippet substitution.
    """
    return get_command_content_structured(tool_info, config).legacy_string


def get_command_content_structured(
    tool_info: ToolInfo, config: Optional[Config] = None,
):
    """Extract command content as a CommandContent dataclass.

    Returns CommandContent(raw_content, legacy_string, summary_template).
    For rich-format handlers (Write, Edit, Skill), summary_template carries
    a `{snippet}` placeholder so per-channel verbosity can apply truncation
    in the formatter dispatch. For non-rich handlers, summary_template is
    None and the legacy_string IS the content (no per-channel truncation).
    """
    from cclogger.models import CommandContent

    tool_input = tool_info.input

    if tool_info.name in ("Bash", "PowerShell"):
        cmd = tool_input.get("command", "")
        return CommandContent(raw_content=cmd, legacy_string=cmd, summary_template=None)

    elif tool_info.name == "Read":
        path = tool_input.get("file_path", "")
        offset = tool_input.get("offset")  # Line number to start from
        limit = tool_input.get("limit")    # Number of lines to read

        if not path:
            return CommandContent(raw_content="", legacy_string="", summary_template=None)

        # Build path with line info for VS Code clickability
        if offset:
            if limit:
                end_line = offset + limit - 1
                path_display = f"{path}:{offset}-{end_line}"
            else:
                path_display = f"{path}:{offset}"
        else:
            path_display = path

        if limit and not offset:
            s = f'"{path_display}" ({limit}L)'
        else:
            s = f'"{path_display}"'
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name == "Write":
        path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        line_count = len(content.splitlines()) if content else 0
        line_info = f" ({line_count}L)" if line_count > 0 else ""
        if path and content:
            preview = truncate_preview(content, config=config)
            legacy = f'"{path}" ← "{preview}"{line_info}'
            template = f'"{path}" ← "{{snippet}}"{line_info}'
            return CommandContent(raw_content=content, legacy_string=legacy, summary_template=template)
        s = f'"{path}"' if path else ""
        return CommandContent(raw_content=content, legacy_string=s, summary_template=None)

    elif tool_info.name == "Edit":
        path = tool_input.get("file_path", "")
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        old_lines = len(old_string.splitlines()) if old_string else 0
        new_lines = len(new_string.splitlines()) if new_string else 0
        if old_lines == new_lines:
            line_info = f" ({new_lines}L)" if new_lines > 0 else ""
        else:
            line_info = f" (-{old_lines}/+{new_lines}L)"
        line_num = find_line_number(path, new_string, config=config) if path and new_string else None
        path_with_line = f"{path}:{line_num}" if line_num else path
        if path and new_string:
            preview = truncate_preview(new_string, config=config)
            legacy = f'"{path_with_line}" ← "{preview}"{line_info}'
            template = f'"{path_with_line}" ← "{{snippet}}"{line_info}'
            return CommandContent(raw_content=new_string, legacy_string=legacy, summary_template=template)
        s = f'"{path_with_line}"' if path else ""
        return CommandContent(raw_content=new_string, legacy_string=s, summary_template=None)

    elif tool_info.name == "MultiEdit":
        path = tool_input.get("file_path", "")
        s = f'"{path}"' if path else ""
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name == "TodoWrite":
        todos = tool_input.get("todos", [])
        s = json.dumps(todos, separators=(",", ":"))
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name == "LS":
        path = tool_input.get("path", "")
        s = f'"{path}"' if path else ""
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name == "Glob":
        pattern = tool_input.get("pattern", "")
        search_path = tool_input.get("path", "")
        s = f'{pattern} in "{search_path}"' if search_path else pattern
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name == "Grep":
        pattern = tool_input.get("pattern", "")
        glob_filter = tool_input.get("glob", "")
        search_path = tool_input.get("path", "")

        result = pattern
        if glob_filter:
            result += f' | "{glob_filter}"'

        if search_path:
            cwd = tool_info.raw_json.get("cwd", "")
            separator = " in " if glob_filter else " | "
            try:
                search_path_obj = Path(search_path).resolve()
                cwd_obj = Path(cwd).resolve() if cwd else None

                if search_path_obj.is_file():
                    result += f'{separator}"{search_path_obj}"'
                elif cwd_obj and search_path_obj != cwd_obj:
                    try:
                        rel = search_path_obj.relative_to(cwd_obj)
                        result += f'{separator}"{rel}/"'
                    except ValueError:
                        result += f'{separator}"{search_path_obj}"'
            except Exception:
                result += f'{separator}"{search_path}"'

        return CommandContent(raw_content=result, legacy_string=result, summary_template=None)

    elif tool_info.name in ("WebSearch", "WebFetch"):
        s = tool_input.get("url") or tool_input.get("query", "")
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name in ("EnterPlanMode", "ExitPlanMode"):
        return CommandContent(raw_content="", legacy_string="", summary_template=None)

    elif tool_info.name == "TaskOutput":
        # #87 follow-up: extract tool_response.task.output AND emit a
        # `{snippet}` template so per-channel max_chars actually applies.
        # Without the template, DefaultFormatter takes the legacy_complete
        # bypass at default.py:60-62 -- no truncation, sesslog and tools
        # produce byte-identical output. With the template, the snippet
        # portion is truncated per channel while `#{task_id} -> ` prefix
        # stays intact for identification.
        task_id = tool_input.get("task_id", "")
        response_task = (tool_info.raw_json.get("tool_response") or {}).get("task") or {}
        output = response_task.get("output", "")
        if output:
            template = f"#{task_id} -> {{snippet}}"
            legacy = f"#{task_id} -> {output}"
            return CommandContent(raw_content=output, legacy_string=legacy, summary_template=template)
        s = f"#{task_id}"
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name == "TaskStop":
        # #87 follow-up: include tool_response.message so the entry shows
        # outcome (e.g., "Task 42 stopped successfully"), not just the id.
        task_id = tool_input.get("task_id", "")
        response = tool_info.raw_json.get("tool_response") or {}
        message = response.get("message", "")
        if message:
            s = f"#{task_id} | {message}"
        else:
            s = f"#{task_id}"
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name in ("tool_search_tool_regex", "tool_search_tool_bm25"):
        s = tool_input.get("query", "")
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name == "Task":
        s = tool_input.get("prompt", "")
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    elif tool_info.name == "Skill":
        # Skill keeps its own preview length (config.performance.skill_args_length,
        # default 100) — distinct from the global content_preview_length (default 20).
        # We pre-truncate at handler time and skip the {snippet} template path so
        # the per-channel verbosity walk doesn't override the Skill-specific budget.
        skill_name = tool_input.get("skill", "")
        skill_args = tool_input.get("args", "")
        max_args = config.performance.skill_args_length if config else 100
        if skill_args and max_args > 0:
            preview = truncate_preview(skill_args, max_len=max_args, config=config)
            legacy = f'{skill_name} ← "{preview}"'
            return CommandContent(raw_content=legacy, legacy_string=legacy, summary_template=None)
        return CommandContent(raw_content=skill_name, legacy_string=skill_name, summary_template=None)

    elif tool_info.name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        s = get_task_content(tool_info.name, tool_info.raw_json, config)
        return CommandContent(raw_content=s, legacy_string=s, summary_template=None)

    else:
        # For unknown tools, try common field names. Order matters: more
        # specific/distinctive fields first so collisions are less likely.
        # `command` covers shell-like tools (Bash/PowerShell pattern), `skill`
        # covers Skill-like, `subject` covers task-like, etc. New tools that
        # match these shapes will "just work" without needing a custom handler.
        for field in ("command", "pattern", "url", "prompt", "query", "skill", "subject", "content"):
            if field in tool_input:
                s = str(tool_input[field])
                return CommandContent(raw_content=s, legacy_string=s, summary_template=None)
        return CommandContent(raw_content="", legacy_string="", summary_template=None)


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


def _role_from_tool_name(tool_name: str) -> str:
    """Map a tool name to a hierarchical role string per ROLES.

    Examples:
      "Bash" -> "bash", "PowerShell" -> "powershell",
      "Edit" -> "edit", "MultiEdit" -> "multi-edit",
      "TodoWrite" -> "todo-write", "WebSearch" -> "web-search".

    Tools not in the ROLES enum get their tool_name normalized to kebab-case;
    Step 10 of Phase 2+3 wires the ??:<role> fallback warning.
    """
    # Camel/PascalCase -> kebab-case for hierarchical role strings
    out_chars: list[str] = []
    for i, ch in enumerate(tool_name):
        if ch.isupper() and i > 0 and tool_name[i - 1].islower():
            out_chars.append("-")
        out_chars.append(ch.lower())
    return "".join(out_chars)


def generate_entry(tool_info: ToolInfo, config: Config, command_content,
                   event_time: datetime):
    """Generate a LogEntry for the tool call.

    Phase 2+3 Step 7: command_content can be a string (legacy callers) or a
    CommandContent dataclass (Phase 2+3 caller in log-command.py). When a
    CommandContent is provided with a non-None summary_template, the LogEntry
    carries the template in `summary` so DefaultFormatter can substitute the
    `{snippet}` placeholder per channel verbosity. The `_legacy_complete`
    metadata is also populated for backward compat — channels with no
    options on a rich-format entry still get byte-identical legacy output.
    """
    from cclogger.models import CommandContent, LogEntry

    if isinstance(command_content, CommandContent):
        cc = command_content
        legacy_string = cc.legacy_string
        raw_content = cc.raw_content
        summary_template = cc.summary_template
    else:
        # Legacy str caller — wrap as a non-rich CommandContent
        legacy_string = command_content
        raw_content = command_content
        summary_template = None

    datetime_part = format_datetime(config.datetime_mode, event_time)

    pwd_part = ""
    if config.pwd_enabled:
        pwd_part = f' ["{os.getcwd()}"]'

    # Get tool name with agent context
    tool_display = format_tool_name(tool_info)

    # Prefix uncategorized tools with `?` for grep-friendly identification
    # within any channel. Pattern remains parseable: `{?ToolName: ...}`.
    is_unknown = categorize_tool(tool_info.name) == "unknown"
    if is_unknown:
        tool_display = f"?{tool_display}"

    # Determine the legacy body content based on verbosity + action-only.
    # This builds the v0.3.6-shaped string used to populate _legacy_complete
    # so non-rich entries (and channels with no options) stay byte-identical.
    if should_use_action_only(tool_info.name, config):
        legacy_body = tool_display
    else:
        if config.verbosity == 0:
            legacy_body = legacy_string
        elif config.verbosity == 1:
            legacy_body = legacy_string
        elif config.verbosity == 2:
            legacy_body = f"{tool_display}: {legacy_string}"
        elif config.verbosity == 3:
            if tool_info.description:
                legacy_body = f"{tool_display}: {legacy_string} {tool_info.description}"
            else:
                legacy_body = f"{tool_display}: {legacy_string}"
        elif config.verbosity == 4:
            tool_input_json = json.dumps(tool_info.input, separators=(",", ":"))
            legacy_body = f"{tool_display}: {legacy_string} {tool_input_json}"
        else:
            legacy_body = f"{tool_display}: {legacy_string}"

    legacy_complete = f"{datetime_part}{{{legacy_body} }}{pwd_part}"

    # Build the LogEntry's `summary` field: when the handler provided a
    # rich-format template, embed it in the same verbosity-shaped body so
    # DefaultFormatter can substitute the snippet per channel verbosity.
    summary: Optional[str] = None
    if summary_template and not should_use_action_only(tool_info.name, config):
        if config.verbosity == 0 or config.verbosity == 1:
            summary = summary_template
        elif config.verbosity == 2:
            summary = f"{tool_display}: {summary_template}"
        elif config.verbosity == 3:
            if tool_info.description:
                summary = f"{tool_display}: {summary_template} {tool_info.description}"
            else:
                summary = f"{tool_display}: {summary_template}"
        elif config.verbosity == 4:
            tool_input_json = json.dumps(tool_info.input, separators=(",", ":"))
            summary = f"{tool_display}: {summary_template} {tool_input_json}"
        else:
            summary = f"{tool_display}: {summary_template}"

    return LogEntry(
        raw_content=raw_content,
        role=_role_from_tool_name(tool_info.name),
        summary=summary,
        metadata={
            "_legacy_complete": legacy_complete,
            "pwd_part": pwd_part,
            "datetime_part": datetime_part,
            "is_unknown_tool": is_unknown,
        },
        timestamp=event_time,
        tool_name=tool_info.name,
        agent_context=tool_info.agent_context,
    )
