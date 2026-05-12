"""ChatFormatter — readable conversation rendering for the convo channel.

Replaces the v0.3.6 hardcoded `truncate_preview(prompt, max_len=200, ...)`
calls in conversation.py. The `convo` channel declares `formatter="chat"` +
`newline_policy=RENDER` in its default ChannelOptions; this formatter
produces multi-line conversation entries that read naturally instead of the
single-line `{USER: "preview…" }` shape the default formatter emits.

Output shape:
    [[<datetime>]] {USER:
    <multi-line content rendered with real newlines per NewlinePolicy.RENDER>
    }

Newline behavior follows NewlinePolicy resolution from channel options. When
RENDER (default for convo), newlines in raw_content render as actual
newlines so the log is readable as a chat transcript. When ESCAPE, falls
back to the same shape but with escaped newlines (grep-friendly).

Verbosity: defaults to "full" for convo so user/AI/agent prose is captured
in its entirety. Per-role overrides apply (e.g., agents could set
`{"agent:user": {"max_chars": 200}}` to truncate user text inside subagents
while keeping AI/agent text full).
"""

from __future__ import annotations

from typing import Any

from cclogger.formatters.base import BaseFormatter
from cclogger.formatters.legacy import format_datetime
from cclogger.models import NewlinePolicy


class ChatFormatter(BaseFormatter):
    """Multi-line readable shape for the convo channel."""

    def format(self, entry: Any) -> str:
        if isinstance(entry, str):
            return entry

        from cclogger.models import LogEntry

        if not isinstance(entry, LogEntry):
            return str(getattr(entry, "summary", "") or getattr(entry, "raw_content", ""))

        role = entry.role or "unknown"
        tool_name = entry.tool_name

        max_chars = self._resolve_max_chars(role, tool_name)
        newline_policy = self._resolve_newlines(role, tool_name)
        label = self._resolve_role_label(role)

        body = self._truncate(entry.raw_content or "", max_chars)

        datetime_mode = "full"
        if self.config is not None:
            try:
                datetime_mode = self.config.datetime_mode
            except AttributeError:
                pass
        datetime_part = format_datetime(datetime_mode, entry.timestamp)

        if newline_policy == NewlinePolicy.RENDER:
            # Multi-line readable: `[[ts]] {USER:\n<body>\n}`
            return f"{datetime_part}{{{label}:\n{body}\n}}"

        # ESCAPE fallback: collapse to single line, same shape as default
        escaped_body = body.replace("\r\n", "\\n").replace("\n", "\\n")
        return f"{datetime_part}{{{label}: {escaped_body} }}"
