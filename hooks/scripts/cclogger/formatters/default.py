"""DefaultFormatter — the v0.3.6 hybrid-json {ROLE: "preview"} shape.

This is the formatter every channel uses unless it explicitly opts into
something else via ChannelOptions.formatter. During Step 3, this class
just serves byte-identical output to the legacy generate_entry path so the
snapshot diff stays clean while later steps wire dispatch through it.

Step 4 introduces LogEntry; this class then knows how to format a LogEntry
into the same legacy shape (plus the new options like NewlinePolicy.RENDER).
Step 5 makes log_entry() call format_for_channel(), routing here by default.
"""

from __future__ import annotations

from typing import Any, Optional

from cclogger.formatters.base import BaseFormatter
from cclogger.formatters.legacy import LABEL_SENTINEL, format_datetime
from cclogger.models import NewlinePolicy


class DefaultFormatter(BaseFormatter):
    """Hybrid-json `{ROLE: "preview"}` formatter.

    Behavior matches v0.3.6 generate_entry() output exactly when given the
    same input. New behavior layered on:
      - per-channel verbosity from ChannelOptions (Step 5+)
      - NewlinePolicy.{ESCAPE, RENDER} application (Step 5+)
      - per-role label overrides via ChannelOptions.role_labels (Step 5+)

    During the cutover, format() accepts either:
      - str (Step 3 stub, returned as-is — byte-identical legacy passthrough)
      - LogEntry (Step 4+, properly assembled per channel options)
    """

    def format(self, entry: Any) -> str:
        # Defensive passthrough for any caller that hasn't been cut over to
        # LogEntry (none currently — conversation.py cut over in Step 6).
        if isinstance(entry, str):
            return entry

        from cclogger.models import LogEntry

        if not isinstance(entry, LogEntry):
            raw = getattr(entry, "summary", None) or getattr(
                entry, "raw_content", ""
            )
            return str(raw)

        # Phase 2+3 Step 7: when entry.summary carries a `{snippet}`
        # placeholder, the handler emitted a rich-format template. Substitute
        # the snippet per channel verbosity, then assemble + apply newline
        # policy. This is the path that lets per-channel options actually
        # affect Edit/Write/Skill rich formatting.
        # #55 / unit 7: the label an in-agent tool entry gets HERE (plain, or
        # the id forms) when it differs from the `always` rendering baked at
        # generation; None means the baked strings already say it.
        label = self._tool_label(entry)

        if entry.summary and "{snippet}" in entry.summary:
            return self._format_template_entry(entry, label=label)

        # No template: precomputed legacy_complete (Bash, Read, Grep, ...)
        # has the full byte-identical legacy string. Use it directly.
        legacy_complete = entry.metadata.get("_legacy_complete")
        if label is not None:
            template = entry.metadata.get("_legacy_complete_t")
            if isinstance(template, str):
                legacy_complete = template.replace(LABEL_SENTINEL, label)
        if isinstance(legacy_complete, str):
            return legacy_complete

        # No template + no legacy_complete: pure raw_content path
        # (conversation.py LogEntries from Step 6 take this branch).
        return self._format_log_entry(entry)

    def _format_template_entry(self, entry: "LogEntry",
                               label: Optional[str] = None) -> str:
        """Substitute `{snippet}` in entry.summary per channel verbosity.

        Output: `[[<datetime>]] {<substituted-summary> }<pwd_part>`
        Byte-identical to _legacy_complete when channel has no options
        (snippet truncated + escaped to match legacy truncate_preview).
        `label`, when given, is this channel's form of an in-agent tool
        label, filled into the sentinel template baked beside the summary.
        """
        from cclogger.formatters.legacy import format_datetime

        role = entry.role or "unknown"
        tool_name = entry.tool_name

        max_chars = self._resolve_max_chars(role, tool_name)
        newline_policy = self._resolve_newlines(role, tool_name)

        # Snippet uses the legacy preview semantics (escape-then-truncate
        # under ESCAPE; truncate-only under RENDER). The surrounding
        # template (path:line, line delta, etc.) is already final ASCII
        # and not subject to per-channel escape.
        snippet = self._preview_for_display(
            entry.raw_content or "", max_chars, newline_policy
        )
        template = entry.summary
        if label is not None:
            labelled = entry.metadata.get("summary_t")
            if isinstance(labelled, str) and "{snippet}" in labelled:
                template = labelled.replace(LABEL_SENTINEL, label)
        body = template.replace("{snippet}", snippet)

        # Use pre-computed datetime + pwd from generate_entry metadata
        # to preserve byte-identity with legacy_complete in default channels
        datetime_part = entry.metadata.get("datetime_part")
        if datetime_part is None:
            datetime_mode = "full"
            if self.config is not None:
                try:
                    datetime_mode = self.config.datetime_mode
                except AttributeError:
                    pass
            datetime_part = format_datetime(datetime_mode, entry.timestamp)
        pwd_part = entry.metadata.get("pwd_part", "")

        return f"{datetime_part}{{{body} }}{pwd_part}"

    def _format_log_entry(self, entry: "LogEntry") -> str:
        """Assemble the hybrid-json shape from a LogEntry per channel options.

        Output shape: `[[<datetime>]] {<LABEL>: <body> }`
        Where <body> is either:
          - the summary template with {snippet} substituted by the
            verbosity-truncated raw_content (per-tool rich format path), or
          - the truncated raw_content directly (no-template path)

        NewlinePolicy applied after assembly so it covers both summary and
        raw content uniformly.
        """
        role = entry.role or "unknown"
        tool_name = entry.tool_name

        # Resolve channel options
        max_chars = self._resolve_max_chars(role, tool_name)
        newline_policy = self._resolve_newlines(role, tool_name)
        # Thinking entries display under think / agent-think (2026-09-03);
        # verbosity and newlines above still resolve on the entry's own role.
        label = self._resolve_role_label(self._display_role(entry))

        # #50: agent-role entries carry the agent's identity in the label
        # (`{AGENT:explore ...}`), mode-gated per ChannelOptions.agent_label.
        if role in ("agent", "agent-start", "agent-stop"):
            identity = self._agent_identity_for_display(entry)
            if identity:
                label = f"{label}:{identity}"

        # Determine body content (+ the full agent id once, on the bracket
        # lines, under the id label modes -- unit 7)
        body = self._build_body(entry, max_chars) + self._agent_id_suffix(entry)

        # Datetime prefix
        datetime_mode = "full"
        if self.config is not None:
            try:
                datetime_mode = self.config.datetime_mode
            except AttributeError:
                pass
        datetime_part = format_datetime(datetime_mode, entry.timestamp)

        # Assemble entry. Note the trailing space inside the brace:
        # `{LABEL: body }` matches legacy generate_entry() output exactly.
        assembled = f"{datetime_part}{{{label}: {body} }}"

        # Apply newline policy across the whole entry
        return self._apply_newline_policy(assembled, newline_policy)

    def _build_body(self, entry: "LogEntry", max_chars: int) -> str:
        """Build the entry body from raw_content + summary template.

        Three cases:
          1. summary template with {snippet} placeholder — substitute the
             truncated raw_content into the template
          2. summary template without {snippet} — use as-is
             (e.g., Read which already has full context)
          3. no summary at all — use truncated raw_content directly
        """
        raw = entry.raw_content or ""
        summary = entry.summary or ""

        if summary and "{snippet}" in summary:
            snippet = self._truncate(raw, max_chars)
            return summary.replace("{snippet}", snippet)

        if summary:
            return summary

        return self._truncate(raw, max_chars)
