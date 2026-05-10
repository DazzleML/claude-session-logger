"""Data classes used across cclogger.

ToolInfo describes the JSON input from Claude Code; PerformanceConfig,
ChannelConfig, RoutingConfig, and Config carry user-configurable settings;
SessionContext supplies filename pieces; LogEntry is the (currently dead,
to be repurposed in v0.3.7) wrapper for a formatted entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from cclogger.debug import debug_log


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
    """Configuration for a single log channel."""
    file_prefix: str
    enabled: bool = True


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
    """Represents a formatted log entry."""

    timestamp: Optional[datetime]
    tool_name: str
    content: str
    pwd: Optional[str]
    is_failure: bool = False
    failure_reason: Optional[str] = None
    error_output: Optional[str] = None
