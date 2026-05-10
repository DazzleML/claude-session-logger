"""Tool name → category mapping + per-category subtype extraction.

Audit (#29, v0.3.1) for which tools belong in `bash`, `system`, `io`, etc.
Subtype extractors (#31, v0.3.3) yield secondary channel names like
`bash-powershell_*` and `mcp-github_*` when subtype routing is enabled.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from cclogger.debug import debug_log


# ============================================================================
# Tool Categorization
# ============================================================================

# Audit (#29, v0.3.1):
#
# The `bash` category routes to `.shell_*.log` -- the channel that captures
# shell-equivalent operations. The criterion is WORKFLOW context, not strict
# structural compatibility: tools that are conceptually shell-equivalent
# (commands you'd run from a terminal -- ls, grep, glob patterns) belong
# here so investigators can see the full sequence of navigation + execution
# in one place. This is more useful than nitpicking whether the tool input
# is a literal `command` string or a structured query.
#
# Bash-shaped tools (literal shell commands):
#   - Bash, PowerShell -- take `command` field, execute through a shell
#
# Bash-equivalent tools (structured but conceptually shell-style):
#   - Grep -- the equivalent of `grep -r pattern` or `rg pattern`
#   - LS   -- the equivalent of `ls -la` listing
#   - Glob -- the equivalent of shell glob pattern matching `find . -name '*.py'`
#
# What stays in `system` (not bash-equivalent):
#   - Read -- structured file read with offset/limit, not a shell op
#   - EnterPlanMode, ExitPlanMode -- mode markers, no command analog
#
# Override: if a project prefers Grep/LS/Glob NOT in `.shell_*.log`, set
# them via `routing.tool_overrides` to redirect away from shell.
TOOL_CATEGORIES: dict[str, str] = {
    # Shell-style execution (literal commands or shell-equivalent operations)
    "Bash": "bash",
    "PowerShell": "bash",
    "Grep": "bash",   # `grep -r pattern` equivalent (was system pre-v0.3.1)
    "LS": "bash",     # `ls -la` equivalent (was system pre-v0.3.1)
    "Glob": "bash",   # `find . -name '*.py'` equivalent (was system pre-v0.3.1)
    # File system queries (structured input, not shell-equivalent)
    "Read": "system",
    # File I/O
    "Write": "io",
    "Edit": "io",
    "MultiEdit": "io",
    "NotebookEdit": "io",
    # Task management
    "TodoWrite": "todo",
    "TaskCreate": "task",
    "TaskUpdate": "task",
    "TaskList": "task",
    "TaskGet": "task",
    # Meta/agents
    "Task": "meta",
    # Web interaction
    "WebSearch": "search",
    "WebFetch": "search",
    # User interaction
    "AskUserQuestion": "ui",
    "Skill": "skill",
    # Plan mode (markers, not content)
    "EnterPlanMode": "system",
    "ExitPlanMode": "system",
    # Task output/control
    "TaskOutput": "task",
    "TaskStop": "task",
    # ToolSearch -- dynamic MCP tool discovery
    "tool_search_tool_regex": "search",
    "tool_search_tool_bm25": "search",
}


# Subtype extractors per category (v0.3.3, #31): given the tool name + raw
# JSON payload, return a subtype string used to derive a per-subtype channel
# name (e.g., "powershell" yields .bash-powershell_*.log when bash subtype
# routing is enabled). Returns None if the subtype cannot be determined or
# is not meaningful for this category.
def _subtype_for_bash(tool_name: str, raw_json: dict[str, Any]) -> Optional[str]:
    """For bash category, the tool name itself is the subtype (Bash, PowerShell, etc.)."""
    return tool_name.lower() if tool_name else None


def _subtype_for_mcp(tool_name: str, raw_json: dict[str, Any]) -> Optional[str]:
    """For MCP tools, extract the server name from mcp__servername__toolname."""
    if not tool_name.startswith("mcp__"):
        return None
    parts = tool_name.split("__", 2)
    return parts[1] if len(parts) >= 2 else None


def _subtype_for_meta(tool_name: str, raw_json: dict[str, Any]) -> Optional[str]:
    """For Task subagent invocations, extract the subagent_type."""
    tool_input = raw_json.get("tool_input", {})
    return tool_input.get("subagent_type") or None


def _subtype_for_skill(tool_name: str, raw_json: dict[str, Any]) -> Optional[str]:
    """For Skill invocations, extract the skill name from the input."""
    tool_input = raw_json.get("tool_input", {})
    return tool_input.get("skill") or None


SUBTYPE_EXTRACTORS: dict[str, "Any"] = {
    "bash": _subtype_for_bash,
    "mcp": _subtype_for_mcp,
    "meta": _subtype_for_meta,
    "skill": _subtype_for_skill,
}


def get_subtype(category: str, tool_name: str, raw_json: dict[str, Any]) -> Optional[str]:
    """Get the subtype for a tool, or None if no extractor / no subtype."""
    extractor = SUBTYPE_EXTRACTORS.get(category)
    if extractor is None:
        return None
    try:
        subtype = extractor(tool_name, raw_json)
        if subtype:
            # Sanitize for filesystem safety
            return re.sub(r"[^A-Za-z0-9_\-.]", "_", str(subtype))
        return None
    except Exception:
        return None


def categorize_tool(tool_name: str) -> str:
    """Map tool name to category."""
    # Check for MCP tools (mcp__servername__toolname format)
    if tool_name.startswith("mcp__"):
        return "mcp"

    category = TOOL_CATEGORIES.get(tool_name)
    if category:
        return category

    # Unknown tool - log for visibility and return "unknown"
    # The "unknown" category routes to the dedicated `unknowns` channel
    # (and sesslog) by default, keeping shell-history channel free of
    # uncategorized tools.
    debug_log(f"Unknown tool encountered: {tool_name}, categorizing as 'unknown'")
    return "unknown"
