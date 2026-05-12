"""Formatters package for the v0.3.x logger.

Phase 2+3 (Github #38) splits the original cclogger/formatters.py module into a
package so per-channel formatter dispatch can grow without sprawling the legacy
helpers. Existing per-tool handlers + datetime/role formatters live in
`legacy.py` (relocated unchanged from the v0.3.6 module). New formatter classes
(`default`, `chat`, `task-only`, `jsonl`, `xml`) plus the `format_for_channel`
dispatch entry point will land beside them in subsequent steps of Phase 2+3.

This `__init__.py` re-exports every public + private symbol the rest of the
codebase + tests reach for. New code SHOULD import from
`cclogger.formatters.legacy` (or the future submodules) directly; the
re-exports here exist only so the Phase 2+3 cutover stays mechanical and the
test suite remains green at every intermediate checkpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from cclogger.formatters.legacy import (
    # Filtering helpers
    should_log_tool,
    should_use_action_only,
    # Content extraction
    get_task_content,
    find_line_number,
    truncate_preview,
    get_command_content,
    get_command_content_structured,
    # Entry generation
    format_datetime,
    format_tool_name,
    generate_entry,
    # Channel-options resolution helpers (Phase 1, inert; consumed in Phase 2+3)
    _VERBOSITY_PRESETS,
    _role_prefix_chain,
    _is_hint_dict,
    _verbosity_value_to_int,
    _resolve_verbosity,
    _coerce_newline_policy,
    _resolve_newline_policy,
)

if TYPE_CHECKING:
    from cclogger.models import ChannelOptions, Config, LogEntry


# ============================================================================
# Phase 2+3 dispatch entry point
# ============================================================================
#
# `format_for_channel(entry, channel_opts, channel_name, config)` is the
# single per-channel formatting entry point. Phase 2+3 grows this into a real
# dispatch over the FORMATTERS registry; Step 2 just stubs it as a passthrough
# that returns the legacy string so behavior stays byte-identical while the
# call sites are wired up.
#
# Steps 3+ replace the passthrough with FormatterRegistry-driven dispatch.

from cclogger.formatters.base import BaseFormatter
from cclogger.formatters.chat import ChatFormatter
from cclogger.formatters.default import DefaultFormatter
from cclogger.formatters.task_only import TaskOnlyFormatter


# Formatter registry: name -> formatter class. Subsequent steps add
# JsonlFormatter (stub), XmlFormatter (Step 11 stretch).
FORMATTERS: dict[str, type[BaseFormatter]] = {
    "default": DefaultFormatter,
    "chat": ChatFormatter,
    "task-only": TaskOnlyFormatter,
}


def format_for_channel(
    entry: Any,  # LogEntry once Step 4 lands; str during Step 3 transition
    channel_opts: "Optional[ChannelOptions]",
    channel_name: str,
    config: "Optional[Config]" = None,
) -> str:
    """Format a log entry for a specific channel via the formatter registry.

    Step 3 wires real dispatch through DefaultFormatter. Behavior remains
    byte-identical to the legacy path because:
      - When `entry` is a str (legacy callers from log_entry()), the
        formatter just passes it through.
      - When `entry` is a LogEntry (post-Step-4 callers), the formatter
        assembles per channel options.

    Args:
        entry: The log entry — str during cutover, LogEntry after Step 4.
        channel_opts: Per-channel options from ChannelConfig.options.
        channel_name: Channel name (used for error messages).
        config: Top-level Config (for global defaults).

    Returns:
        The formatted string ready to atomic_append() to the channel file.
    """
    # Resolve formatter class. Default formatter when channel_opts is None
    # OR when channel_opts.formatter is unset/unknown.
    formatter_name = "default"
    if channel_opts is not None and channel_opts.formatter:
        formatter_name = channel_opts.formatter

    formatter_cls = FORMATTERS.get(formatter_name)
    if formatter_cls is None:
        # Unknown formatter -> fall back to default. debug_log warning
        # added in Step 10 alongside the ??:<unknown> role pattern.
        formatter_cls = DefaultFormatter

    formatter = formatter_cls(channel_opts, channel_name, config)
    return formatter.format(entry)


__all__ = [
    "should_log_tool",
    "should_use_action_only",
    "get_task_content",
    "find_line_number",
    "truncate_preview",
    "get_command_content",
    "get_command_content_structured",
    "format_datetime",
    "format_tool_name",
    "generate_entry",
    "format_for_channel",
    "FORMATTERS",
    "_VERBOSITY_PRESETS",
    "_role_prefix_chain",
    "_is_hint_dict",
    "_verbosity_value_to_int",
    "_resolve_verbosity",
    "_resolve_newline_policy",
    "_coerce_newline_policy",
]
