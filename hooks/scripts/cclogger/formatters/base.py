"""Base class + shared helpers for v0.3.7+ formatters.

`BaseFormatter` is the contract every channel formatter implements. Subclasses
override `format()` and may use the shared helpers for verbosity application,
newline-policy handling, and role-label resolution. The dispatch in
`cclogger.formatters.__init__.format_for_channel` instantiates the right
subclass per channel based on `ChannelOptions.formatter`.

Phase 2+3 ships: DefaultFormatter (byte-identical to legacy hybrid-json shape),
ChatFormatter (convo channel), TaskOnlyFormatter (tasks channel), JsonlFormatter
(stub). Future formatters slot in by subclassing this class and registering in
the FORMATTERS dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from cclogger.formatters.legacy import (
    _resolve_newline_policy,
    _resolve_verbosity,
)
from cclogger.models import NewlinePolicy

if TYPE_CHECKING:
    from cclogger.models import ChannelOptions, Config, LogEntry


class BaseFormatter:
    """Contract every channel formatter implements.

    Subclasses override `format()`. Common helpers handle the per-channel
    verbosity walk, newline-policy application, and role-label resolution
    so subclasses can stay focused on their structural shape.
    """

    def __init__(
        self,
        channel_opts: "Optional[ChannelOptions]",
        channel_name: str,
        config: "Optional[Config]" = None,
    ) -> None:
        self.channel_opts = channel_opts
        self.channel_name = channel_name
        self.config = config

    def format(self, entry: Any) -> str:
        """Render the entry for this channel. Override in subclasses."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared helpers (used by subclasses; not for external callers)
    # ------------------------------------------------------------------

    def _agent_identity_for_display(self, entry: Any) -> Optional[str]:
        """#55/#50: the normalized agent identity this channel should show,
        or None when suppressed by ChannelOptions.agent_label:

          "always"  -> show whenever the entry carries agent_context
          "auto"    -> as always, EXCEPT when the identity merely repeats
                       this channel's own subtype suffix (an entry from the
                       Explore agent inside `.agents-explore_*` -- the
                       filename already says who)
          "never"   -> never show
          "id"      -> as always, with the agent's id: ``explore/a7c41e0b``
          "auto-id" -> as auto, with the id; inside `.agents-explore_*` the
                       type is dropped and the id kept: ``a7c41e0b``

        Returns the normalize_subtype() form so displayed identity always
        matches per-agent file naming. The id is its label form (the first
        AGENT_ID_LABEL_CHARS characters -- unit 7, 2026-09-03).

        Untyped bucket (2026-09-02): entries whose classifier is the fixed
        "untyped" bucket carry the id in EVERY mode that shows identity --
        the bucket names a CLASS, and the per-instance id is the only
        attribution the line can carry (no transcript exists for these
        agents): ``untyped/a000e885``, or ``a000e885`` inside
        ``.agents-untyped_*`` under the auto forms. That was the special
        case; the id modes make it the general rule.
        """
        ctx = getattr(entry, "agent_context", None)
        if not ctx:
            return None
        mode = self._agent_label_mode()
        if mode == "never":
            return None
        from cclogger.categorize import normalize_subtype
        from cclogger.models import (
            AGENT_LABEL_AUTO_MODES,
            AGENT_LABEL_ID_MODES,
            UNTYPED_AGENT_CLASSIFIER,
            short_agent_id,
        )
        norm = normalize_subtype(ctx)
        if not norm:
            return None
        repeats_filename = (
            mode in AGENT_LABEL_AUTO_MODES and self.channel_name.endswith(f"-{norm}")
        )
        with_id = mode in AGENT_LABEL_ID_MODES or norm == UNTYPED_AGENT_CLASSIFIER
        short = short_agent_id(getattr(entry, "agent_id", None)) if with_id else None
        if short:
            return short if repeats_filename else f"{norm}/{short}"
        if repeats_filename:
            return None
        return norm

    def _agent_label_mode(self) -> str:
        """This channel's ChannelOptions.agent_label, defaulting to always."""
        if self.channel_opts is None:
            return "always"
        return getattr(self.channel_opts, "agent_label", "always") or "always"

    def _tool_label(self, entry: Any) -> Optional[str]:
        """The label a tool entry made INSIDE an agent gets in this channel,
        or None when the strings baked at generation already say it.

        generate_entry bakes the `always` rendering (`{Bash|Explore: ...}`,
        the v0.3.6 case preserved byte for byte) plus a template with a
        label sentinel. The three other forms are this channel's to fill:
        `Bash` (never, or auto inside the agent's own file), and under the
        id modes `Bash|explore/a7c41e0b` or, inside the agent's own file,
        `Bash|a7c41e0b` -- the same identity the prose labels show.
        """
        if not getattr(entry, "agent_context", None):
            return None
        metadata = getattr(entry, "metadata", None)
        base = metadata.get("tool_display_base") if isinstance(metadata, dict) else None
        if not isinstance(base, str):
            return None
        identity = self._agent_identity_for_display(entry)
        if identity is not None and self._agent_label_mode() in ("always", "auto"):
            return None
        return f"{base}|{identity}" if identity else base

    def _agent_id_suffix(self, entry: Any) -> str:
        """Under the id modes the START/STOP bracket lines carry the full id
        once, inside the frame (` [id a7c41e0b9d2f53e18]`), so the short form
        on every other line maps back without leaving the log. Empty for
        every other role and mode."""
        if getattr(entry, "role", None) not in ("agent-start", "agent-stop"):
            return ""
        from cclogger.models import AGENT_LABEL_ID_MODES
        if self._agent_label_mode() not in AGENT_LABEL_ID_MODES:
            return ""
        agent_id = getattr(entry, "agent_id", None)
        return f" [id {agent_id}]" if agent_id else ""

    def _resolve_max_chars(self, role: str, tool_name: Optional[str]) -> int:
        """Return effective max_chars for this entry per channel options.

        0 means no truncation; positive int means "truncate to N chars".
        Negative values are sentinels (Phase 2+3 only uses -1 for "name-only"
        which subclasses interpret structurally rather than via length).
        """
        global_default = 20  # PerformanceConfig.content_preview_length default
        if self.config is not None:
            try:
                global_default = self.config.performance.content_preview_length
            except AttributeError:
                pass
        if self.channel_opts is None:
            return global_default
        return _resolve_verbosity(
            self.channel_opts, role, tool_name, global_default
        )

    def _resolve_newlines(
        self, role: str, tool_name: Optional[str]
    ) -> NewlinePolicy:
        """Return effective NewlinePolicy for this entry per channel options."""
        if self.channel_opts is None:
            return NewlinePolicy.ESCAPE
        return _resolve_newline_policy(self.channel_opts, role, tool_name)

    def _resolve_role_label(self, role: str) -> str:
        """Return the display label for `role`, honoring per-channel overrides.

        Walks the role chain most-specific-first looking for a per-channel
        role_labels override. Falls back to the global ROLE_LABELS dict, then
        to a TitleCase of the role name, then to "??:<role>" for unknown
        roles (Phase 2+3 Step 10 wires the throttled warning).
        """
        from cclogger.formatters.legacy import _role_prefix_chain
        from cclogger.models import ROLE_LABELS, ROLES

        chain = _role_prefix_chain(role)

        # Per-channel role_labels override (most-specific match wins)
        if self.channel_opts is not None and self.channel_opts.role_labels:
            for r in chain:
                if r in self.channel_opts.role_labels:
                    return self.channel_opts.role_labels[r]

        # Global ROLE_LABELS dict (most-specific match wins)
        for r in chain:
            if r in ROLE_LABELS:
                return ROLE_LABELS[r]

        # Known role without a label override -> TitleCase
        if role in ROLES:
            return role.replace("-", " ").title().replace(" ", "")

        # Phase 2+3 Step 10: unknown role surfaces as `??:<role>` AND triggers a
        # throttled debug-log warning (sibling sentinel dir to unknown-tool).
        # Walk the role chain — emit warning only when no segment matches a
        # known role. Avoids spurious warnings for valid hierarchical roles
        # like "agent:senior-engineer:user" where the leaf is novel but the
        # parent is known.
        from cclogger.debug import _warn_unknown_role_once
        _warn_unknown_role_once(role)
        return f"??:{role}"

    # Entry framing (2026-09-03): the body of an entry is always verbatim.
    # Frame integrity for a body with unmatched braces is added OUTSIDE the
    # frame, once, at dispatch (formatters.format_for_channel ->
    # cclogger.frame.pad_frame), never here.

    def _display_role(self, entry: Any) -> str:
        """The role whose label this entry displays under (2026-09-03).

        The entry's own role ("ai", "agent", ...) keeps driving verbosity
        and newline resolution; a thinking entry (LogEntry.kind ==
        "thinking") displays under "think" (main thread) or "agent-think"
        (inside an agent) instead, so per-channel role_labels can rename
        either. Everything else displays under its own role.
        """
        role = getattr(entry, "role", None) or "unknown"
        if getattr(entry, "kind", None) == "thinking":
            if role == "agent":
                return "agent-think"
            if role == "ai":
                return "think"
        return role

    def _apply_newline_policy(
        self, text: str, policy: NewlinePolicy
    ) -> str:
        """Render newlines per policy. ESCAPE -> literal "\\n"; RENDER -> real."""
        if policy == NewlinePolicy.RENDER:
            # Real newlines (multi-line output, conversation-friendly)
            return text
        # ESCAPE (default, grep-friendly): collapse newlines to literal \n
        return text.replace("\r\n", "\\n").replace("\n", "\\n")

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate text to max_chars; 0 = no truncation; <0 = empty (name-only)."""
        if max_chars <= 0:
            # 0 = full content (no truncation)
            # <0 = name-only sentinel (subclass should not have called this)
            return text if max_chars == 0 else ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."

    def _preview_for_display(
        self, text: str, max_chars: int, newline_policy: NewlinePolicy
    ) -> str:
        """Match v0.3.6 truncate_preview() byte-for-byte under ESCAPE.

        Legacy `truncate_preview()` escapes newlines + non-printable chars
        FIRST, then truncates. The visual length depends on the escaped
        form, so byte-identity for default channels requires the same
        order. RENDER policy skips escaping (preserves real newlines for
        the chat formatter's multi-line shape).
        """
        if not text:
            return ""

        if newline_policy == NewlinePolicy.RENDER:
            return self._truncate(text, max_chars)

        # ESCAPE preprocessing — matches legacy truncate_preview semantics
        escaped = text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "")
        escaped = "".join(c if c.isprintable() or c == " " else "?" for c in escaped)
        return self._truncate(escaped, max_chars)
