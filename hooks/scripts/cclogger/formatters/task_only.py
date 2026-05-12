"""TaskOnlyFormatter — emits the `tasks` channel format.

Replaces the v0.3.6 hardcoded `if channel_name == "tasks" and task_content`
branch in SessionLogger.log_entry. The `tasks` channel now declares
`formatter="task-only"` in its default ChannelOptions; this formatter
produces the same output the hardcode used to.

Output shape: `[[<datetime>]] {<task_content_string> }`
where task_content is whatever `get_task_content()` returns
(e.g., `"TaskCreate: id=#42 ← \"Refactor formatter dispatch\""`).

For non-task tools routed to the tasks channel (rare; only if user
overrides routing), this formatter falls back to the LogEntry's
`metadata['_legacy_complete']` if present, else the summary, else
the raw_content.
"""

from __future__ import annotations

from typing import Any

from cclogger.formatters.base import BaseFormatter
from cclogger.formatters.legacy import format_datetime, get_task_content


class TaskOnlyFormatter(BaseFormatter):
    """Emits task-specific entries for the .tasks_*.log channel."""

    def format(self, entry: Any) -> str:
        if isinstance(entry, str):
            return entry

        from cclogger.models import LogEntry

        if not isinstance(entry, LogEntry):
            return str(getattr(entry, "summary", "") or getattr(entry, "raw_content", ""))

        # Try to extract task_content from metadata (handler-precomputed)
        # Falls back to recomputing from raw_json in metadata if needed.
        task_content = entry.metadata.get("task_content")
        if not task_content and entry.tool_name:
            raw_json = entry.metadata.get("raw_json")
            if raw_json is not None:
                task_content = get_task_content(entry.tool_name, raw_json, self.config)

        if not task_content:
            # Non-task entry routed here (unusual). Fall back to the legacy
            # complete string if present, else summary, else raw_content.
            legacy = entry.metadata.get("_legacy_complete")
            if isinstance(legacy, str):
                return legacy
            return entry.summary or entry.raw_content or ""

        # Standard task-only output: same shape the hardcoded branch used to emit.
        datetime_mode = "full"
        if self.config is not None:
            try:
                datetime_mode = self.config.datetime_mode
            except AttributeError:
                pass
        datetime_part = format_datetime(datetime_mode, entry.timestamp)
        return f"{datetime_part}{{{task_content} }}"
