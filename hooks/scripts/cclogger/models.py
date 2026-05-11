"""Data classes used across cclogger.

ToolInfo describes the JSON input from Claude Code; PerformanceConfig,
ChannelConfig (with its v0.3.7 ChannelOptions), RoutingConfig, and Config
carry user-configurable settings; SessionContext supplies filename pieces;
LogEntry (repurposed in v0.3.7) carries structured content from handlers
to formatters. NewlinePolicy + ChannelOptions enable per-channel formatting
without touching handler code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union

from cclogger.debug import debug_log


# ============================================================================
# Channel-options framework constants (v0.3.7)
# ============================================================================

# Reserved keyword discriminator for verbosity dict shape:
#   {"max_chars": 100}                          → hint dict (one of the keys is reserved)
#   {"agent:user": "preview", "ai": "full"}     → per-role map (no reserved keys)
# A user attempting to use a reserved keyword as a role name is rejected by
# config validation (see cclogger/config.py).
RESERVED_VERBOSITY_KEYS: set[str] = {"max_chars", "max_lines"}

# Closed enum of role identifiers handlers can emit. Roles are hierarchical
# with `:` separator (e.g., "agent:senior-engineer:user", "bash:powershell").
# Unknown roles get the `??:<role>` prefix in default formatter output and
# trigger a sentinel-throttled warning to ~/.claude/logs/.unknown_role_warnings/.
# Extend this set when adding new tool handlers or agent types.
ROLES: set[str] = {
    # Conversation roles (top-level — sub-roles via :)
    "user", "ai", "agent",
    # Tool roles — bash category
    "bash",
    # Tool roles — system category
    "read", "enter-plan-mode", "exit-plan-mode",
    # Tool roles — io category
    "write", "edit", "multi-edit", "notebook-edit",
    # Tool roles — task category
    "task-create", "task-update", "task-list", "task-get",
    "task-output", "task-stop", "todo-write",
    # Tool roles — meta category (Task subagent invocation)
    "task",
    # Tool roles — search category
    "web-search", "web-fetch", "glob", "grep",
    "tool-search-tool-regex", "tool-search-tool-bm25",
    # Tool roles — ui / skill / mcp categories
    "ask-user-question", "skill", "mcp",
}

# Display label for each role (default formatter uses these to produce
# {LABEL: ...} headers). Per-channel overrides via ChannelOptions.role_labels.
ROLE_LABELS: dict[str, str] = {
    # Conversation: ALL CAPS per current convo channel convention
    "user": "USER",
    "ai": "AI",
    "agent": "AGENT",
    # Tools: Title-Case (matches current `{Edit: ...}` shape)
    "bash": "Bash",
    "read": "Read",
    "enter-plan-mode": "EnterPlanMode",
    "exit-plan-mode": "ExitPlanMode",
    "write": "Write",
    "edit": "Edit",
    "multi-edit": "MultiEdit",
    "notebook-edit": "NotebookEdit",
    "task-create": "TaskCreate",
    "task-update": "TaskUpdate",
    "task-list": "TaskList",
    "task-get": "TaskGet",
    "task-output": "TaskOutput",
    "task-stop": "TaskStop",
    "todo-write": "TodoWrite",
    "task": "Task",
    "web-search": "WebSearch",
    "web-fetch": "WebFetch",
    "glob": "Glob",
    "grep": "Grep",
    "tool-search-tool-regex": "ToolSearchRegex",
    "tool-search-tool-bm25": "ToolSearchBM25",
    "ask-user-question": "AskUserQuestion",
    "skill": "Skill",
    "mcp": "MCP",
}


class NewlinePolicy(Enum):
    """How a formatter handles newlines in entry content.

    Sub-option of formatters that support it (currently `default`); other
    formatters (`chat`, `xml`, `jsonl`) have intrinsic newline behavior
    dictated by the format itself and ignore this setting.
    """
    ESCAPE = "escape"   # \n → literal "\n" in output (escape codes visible; grep-friendly single line)
    RENDER = "render"   # \n → actual newline in output (multi-line, readable)


@dataclass
class ChannelOptions:
    """Per-channel formatting + behavior knobs (v0.3.7).

    All fields are optional. None defaults mean "fall through to global
    default" (verbosity → PerformanceConfig.content_preview_length;
    newline_policy → ESCAPE). The `formatter` field defaults to "default"
    (the current `{ROLE: content}` hybrid-json shape) so unconfigured
    channels keep current behavior.

    Verbosity field shapes:
      - "full" / "preview" / "name-only"          (preset string)
      - {"max_chars": 100} / {"max_lines": 5}     (hint dict; reserved keys)
      - {"agent:user": "preview", ...}            (per-role map; arbitrary keys)
      - {"PowerShell": {"max_chars": 50}, ...}    (per-tool override at level 1
                                                   of the 5-level hierarchy)

    Newline_policy follows the same shapes (NewlinePolicy enum value, string,
    or per-role map of either).
    """
    verbosity: Optional[Union[str, dict]] = None
    formatter: str = "default"
    newline_policy: Optional[Union[NewlinePolicy, str, dict]] = None
    role_labels: Optional[dict[str, str]] = None  # per-channel override of global ROLE_LABELS
    suppress_markers: bool = False  # opt out of session-marker broadcast (v0.3.7 #39)


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class ToolInfo:
    """Information extracted from Claude Code's JSON input."""

    name: str
    input: dict[str, Any]
    description: str
    session_id: str
    transcript_path: str
    raw_json: dict[str, Any]
    agent_context: Optional[str] = None  # Subagent type if running in an agent

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ToolInfo:
        """Create ToolInfo from JSON input."""
        # Detect agent context from various possible fields
        agent_context = cls._detect_agent_context(data)

        return cls(
            name=data.get("tool_name", ""),
            input=data.get("tool_input", {}),
            description=data.get("tool_description", ""),
            session_id=data.get("session_id", "unknown"),
            transcript_path=data.get("transcript_path", ""),
            raw_json=data,
            agent_context=agent_context,
        )

    @staticmethod
    def _detect_agent_context(data: dict[str, Any]) -> Optional[str]:
        """Detect if this tool call is from a subagent and return agent type.

        Checks various possible fields that might indicate agent context.
        Returns the agent type (e.g., "Explore", "Plan") or None if main session.
        """
        # Check for explicit agent context fields (these are speculative -
        # we'll refine based on actual JSON structure observed in debug logs)
        possible_fields = [
            "subagent_type",
            "agent_type",
            "agent_context",
            "parent_agent",
            "spawned_by",
        ]

        for field in possible_fields:
            value = data.get(field)
            if value:
                debug_log(f"Found agent context field '{field}': {value}")
                return str(value)

        # Check for nested agent info
        if "agent" in data and isinstance(data["agent"], dict):
            agent_type = data["agent"].get("type") or data["agent"].get("subagent_type")
            if agent_type:
                debug_log(f"Found nested agent type: {agent_type}")
                return str(agent_type)

        # Check tool_params for agent context (Task tool stores subagent_type there)
        tool_params = data.get("tool_params", {})
        if isinstance(tool_params, dict):
            agent_type = tool_params.get("subagent_type")
            if agent_type:
                debug_log(f"Found agent type in tool_params: {agent_type}")
                return str(agent_type)

        return None


# ============================================================================
# Configuration Data Classes
# ============================================================================

@dataclass
class PerformanceConfig:
    """Performance tuning settings."""
    max_file_size_for_line_search: int = 2 * 1024 * 1024  # 2MB
    content_preview_length: int = 20
    task_description_length: int = 0  # 0 = full (no truncation)
    skill_args_length: int = 100  # 0 = name only, 100 = default preview


@dataclass
class ChannelConfig:
    """Configuration for a single log channel.

    `file_prefix` and `enabled` stay top-level for ergonomics + JSON
    backwards compatibility. v0.3.7 adds `options: ChannelOptions` for
    per-channel verbosity, formatter, newline policy, and role labels.
    """
    file_prefix: str
    enabled: bool = True
    options: ChannelOptions = field(default_factory=ChannelOptions)


def _default_channels() -> dict[str, ChannelConfig]:
    """Create default channel configurations."""
    return {
        "shell": ChannelConfig(file_prefix=".shell_"),
        "sesslog": ChannelConfig(file_prefix=".sesslog_"),
        "tasks": ChannelConfig(file_prefix=".tasks_"),
        "unknowns": ChannelConfig(file_prefix=".unknowns_"),
        # AI-activity-without-prose investigation view. Captures everything
        # the OLD pre-v0.2.1 .sesslog_* did (shell + tools + tasks + skills)
        # but excludes unknowns and user/AI conversation prose.
        # The user's primary "find exact tool calls" channel.
        "tools": ChannelConfig(file_prefix=".tools_"),
        # Conversation channel (sub-issues #33-#35): captures user prompts,
        # AI text responses, and agent dialogue via the message_user /
        # message_ai / message_agent categories. Enabled by default.
        "convo": ChannelConfig(file_prefix=".convo_"),
    }


def _default_category_routes() -> dict[str, list[str]]:
    """Create default category to channel routing."""
    return {
        # Most categories now route to tools as well as shell + sesslog.
        # `tools` provides the AI-activity investigation view; `sesslog` is
        # the kitchen-sink "everything" channel; `shell` stays the clean
        # shell-history channel.
        "_default": ["shell", "sesslog", "tools"],
        "task": ["shell", "sesslog", "tools", "tasks"],
        # Uncategorized tools go to sesslog and to a dedicated unknowns
        # channel for discovery. NOT routed to shell or tools.
        "unknown": ["sesslog", "unknowns"],
        # Conversation categories (sub-issues #33-#35): user prompts, AI
        # text responses, agent dialogue. Route to sesslog (kitchen sink)
        # AND the dedicated convo channel. NOT routed to shell, tools, or
        # tasks -- prose belongs in its own channel.
        "message_user": ["sesslog", "convo"],
        "message_ai": ["sesslog", "convo"],
        "message_agent": ["sesslog", "convo"],
    }


@dataclass
class RoutingConfig:
    """Log routing configuration."""
    channels: dict[str, ChannelConfig] = field(default_factory=_default_channels)
    category_routes: dict[str, list[str]] = field(default_factory=_default_category_routes)
    tool_overrides: dict[str, list[str]] = field(default_factory=dict)
    # Subtype routing (v0.3.3, #31): per-category opt-in for splitting entries
    # into per-subtype channels like .bash-powershell_*, .mcp-github_*, etc.
    # Value can be:
    #   False (default for all) -- no subtype split
    #   True -- split for ALL subtypes encountered
    #   list[str] -- split only for these specific subtypes
    # Categories not present in this dict default to False.
    subtype_routing: dict[str, "bool | list[str]"] = field(default_factory=dict)


@dataclass
class Config:
    """Logger configuration with all settings."""

    # Display settings
    verbosity: int = 2
    datetime_mode: str = "full"  # "full", "date", "none"
    pwd_enabled: bool = False
    filter_include: list[str] = field(default_factory=list)

    # Action-only settings by category
    action_only: dict[str, bool] = field(
        default_factory=lambda: {
            "io": False,
            "bash": False,
            "todo": True,
            "task": False,
            "system": False,
            "meta": False,
            "search": False,
        }
    )

    # Per-tool overrides ("true", "false", or "use_category")
    action_only_overrides: dict[str, str] = field(
        default_factory=lambda: {"TodoWrite": "use_category"}
    )

    # Failure capture settings
    failure_capture_enabled: bool = False
    failure_capture_stderr: bool = True
    failure_capture_max_lines: int = 50

    # NEW: Performance settings
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)

    # NEW: Routing configuration
    routing: RoutingConfig = field(default_factory=RoutingConfig)


@dataclass
class SessionContext:
    """Session identification for file naming."""

    shell_type: str
    session_name: Optional[str]
    session_id: str
    username: str

    def get_filename_context(self) -> str:
        """Generate filename context string.

        Format (with name): {shell}__{name}__{session_id}_{username}
        Format (without):   {shell}_{session_id}_{username}
        """
        if self.session_name:
            return f"{self.shell_type}__{self.session_name}__{self.session_id}_{self.username}"
        else:
            return f"{self.shell_type}_{self.session_id}_{self.username}"

    def get_task_filename_context(self) -> str:
        """Generate task filename context.

        Delegates to get_filename_context() to ensure naming consistency
        across all channels. The channel prefix (.tasks_ vs .sesslog_)
        provides file type differentiation.

        Previously used __ (double underscore) before username which
        diverged from build_filename() causing file proliferation (#15).
        """
        return self.get_filename_context()


@dataclass
class LogEntry:
    """Structured content from a handler, ready for per-channel formatting.

    Repurposed in v0.3.7 (was dead code in v0.3.6 — defined but never
    instantiated). Now the contract between handlers (which know what
    happened) and formatters (which know how to display it for each
    channel). The field set is intentionally rich enough to feed any
    formatter we ship now or later (default, chat, jsonl, xml, custom)
    so future formatter additions don't require handler changes.

    Field semantics:
      raw_content:    full unescaped text (universal — every formatter needs this)
      role:           hierarchical role identifier (e.g., "user", "agent:senior-engineer:ai",
                      "edit", "bash:powershell"). See ROLES.
      summary:        rich format template with `{snippet}` placeholder for the
                      `default` formatter. e.g., '"path:14" ← {snippet} (-2/+3L)'.
                      Other formatters may ignore. None = formatter uses raw_content directly.
      metadata:       formatter-specific extras (path, line, delta, mcp_server, etc.)
      timestamp:      event time (universal)
      tool_name:      original tool name for tool-derived entries (Edit, Bash, ...) — None for prose
      agent_context:  subagent type if relevant
      is_failure:     failure flag (default formatter adds [FAILED:] annotation)
      failure_reason: human-readable reason
      error_output:   captured stderr (multi-line OK)
    """
    raw_content: str
    role: str
    summary: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[datetime] = None
    tool_name: Optional[str] = None
    agent_context: Optional[str] = None
    is_failure: bool = False
    failure_reason: Optional[str] = None
    error_output: Optional[str] = None
