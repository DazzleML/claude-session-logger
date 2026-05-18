"""SessionLogger: per-session log directory + channel routing + marker writing.

Wraps the per-channel write path. On construction it reconciles existing
files for the session (rename unnamed → named, assign --NNN sequences),
writes the SESSION-START / CONTEXT-COMPACTED marker on the first call of a
run, then dispatches each tool entry to the channels chosen by routing
config + subtype expansion.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from cclogger.categorize import get_subtype
from cclogger.debug import debug_log
from cclogger.file_io import (
    atomic_append,
    check_time_gap,
    migrate_overflow_files,
    sweep_orphan_session_name_files,
)
from cclogger.formatters import format_datetime, format_for_channel
from cclogger.markers import (
    count_compaction_markers,
    get_run_number,
    is_new_session_run,
    mark_session_started,
    write_session_marker,
)
from cclogger.models import Config, SessionContext
from cclogger.reconciliation import (
    get_effective_session_name,
    reconcile_session_directory,
    reconcile_session_files,
)


# ============================================================================
# Session Logger
# ============================================================================


class SessionLogger:
    """Main logger class handling all output files."""

    # Prefix removed - Python is now the primary hook
    FILE_PREFIX = ""

    def __init__(self, config: Config, session: SessionContext, event_time: datetime):
        self.config = config
        self.session = session
        self.event_time = event_time
        self.sesslog_base = Path.home() / ".claude" / "sesslogs"
        self.sesslog_base.mkdir(parents=True, exist_ok=True)

        # Get effective session name (from session or existing files/directories)
        self.effective_name = get_effective_session_name(
            session.session_id, session.session_name, self.sesslog_base
        )

        # Build and create session directory
        self.session_dir = self._get_or_create_session_directory()

        # Reconcile files and get target paths (if we have a name)
        self._reconciled = False
        self._target_paths: dict[str, Path] = {}
        if self.effective_name:
            self._reconcile_files()

        # Absorb any legacy `.overflow.N` files from prior versions into
        # their main log files (#47), then sweep up any orphan-session-name
        # files left behind by the pre-fix reconciliation enumeration
        # (Bug B). Both idempotent via per-session-dir sentinels; only
        # scan on first run after upgrade. Must run AFTER `_reconcile_files`
        # (so canonical renames have stabilized) and BEFORE
        # `_maybe_write_session_marker` (so markers land in the merged
        # file with the correct session name).
        if is_new_session_run(self.session.session_id):
            migrate_overflow_files(self.session_dir)
            if self.effective_name:
                sweep_orphan_session_name_files(
                    self.session_dir,
                    self.effective_name,
                    self.session.session_id,
                )

        # Handle session start marker
        self._maybe_write_session_marker()

    def _get_or_create_session_directory(self) -> Path:
        """Get or create the session directory, handling renames if needed.

        Uses unified reconcile_session_directory() which handles:
        1. Directory exists with correct name → return it
        2. Directory exists with wrong name (unnamed or old name) → rename dir + files
        3. No directory exists → create it
        """
        session_dir, _ = reconcile_session_directory(
            self.sesslog_base,
            self.session.session_id,
            self.effective_name,
            self.session.username
        )
        return session_dir

    def _reconcile_files(self) -> None:
        """Reconcile session files (rename unnamed files, assign sequences)."""
        if self._reconciled:
            return

        # Get username from session
        username = self.session.username

        # Reconcile all file categories within the session directory.
        # Pass every declared channel so reconciliation covers tools/convo/
        # unknowns/agents/fileio (Bug B fix, v0.3.7-pre). Subtype derivatives
        # found via filesystem scan are reconciled in-place inside the
        # function and not added to the target-paths dict.
        self._target_paths = reconcile_session_files(
            self.session_dir,
            self.session.session_id,
            self.effective_name,
            self.session.shell_type,
            username,
            channel_names=list(self.config.routing.channels.keys()),
        )
        self._reconciled = True

    def _get_file_path(self, file_type: str) -> Path:
        """Resolve the write path for a base channel.

        Prefers the reconciled path (populated by `_reconcile_files` when
        an effective_name is known). Falls back to building from channel
        config for the unnamed-session case where reconciliation hasn't
        run. Data-driven: any declared channel resolves the same way —
        no special-case branches for shell/sesslog/tasks.
        """
        key = f"{self.FILE_PREFIX}{file_type}"
        if key in self._target_paths:
            return self._target_paths[key]
        return self._get_channel_path(file_type)

    @property
    def shell_log_path(self) -> Path:
        """Path to shell history file (.shell_*)."""
        return self._get_file_path("shell")

    @property
    def unified_log_path(self) -> Path:
        """Path to unified session log (.sesslog_*)."""
        return self._get_file_path("sesslog")

    @property
    def task_log_path(self) -> Path:
        """Path to task history file (.tasks_*)."""
        return self._get_file_path("tasks")

    def _get_channels_for_tool(self, tool_name: str, category: str) -> list[str]:
        """Determine which channels a tool should write to based on routing config.

        Resolution order:
          1. `tool_overrides[tool_name]` -- exact match, REPLACES everything
             (highest precedence; user is being specific)
          2. `category_routes[category]` -- category route (or `_default`
             fallback if category is unknown; `[]` if the user has nuked
             `_default` from their config)
          3. `mcp_server_routes[server]` -- ADDITIVE for `mcp__<server>__*`
             tools (v0.3.7-pre #87). Union the server's channels into the
             route from step 2. Skipped when tool_overrides hit in step 1.
        """
        if tool_name in self.config.routing.tool_overrides:
            return self.config.routing.tool_overrides[tool_name]

        if category in self.config.routing.category_routes:
            channels = list(self.config.routing.category_routes[category])
        else:
            channels = list(self.config.routing.category_routes.get("_default", []))

        if tool_name.startswith("mcp__"):
            parts = tool_name.split("__", 2)
            if len(parts) >= 2:
                server = parts[1]
                extra = self.config.routing.mcp_server_routes.get(server)
                if extra:
                    for ch in extra:
                        if ch not in channels:
                            channels.append(ch)

        return channels

    def _get_channel_path(self, channel_name: str) -> Path:
        """Get file path for a named channel.

        Supports two channel name shapes:
          - declared channel name (e.g., "shell", "sesslog", "tools", "tasks")
            -- file_prefix comes from routing.channels[name].file_prefix
          - "<base>-<subtype>" (e.g., "shell-bash", "agents-help") -- derived
            from a subtype expansion at log time. The base channel must be
            declared; the derived channel inherits its file_prefix with
            `-<subtype>` appended before the trailing underscore.

        All declared channels resolve the same way -- no special-case
        branches for tasks/shell/sesslog. The filename context comes from
        SessionContext.get_filename_context() universally; channel identity
        is carried entirely by file_prefix.
        """
        channel = self.config.routing.channels.get(channel_name)
        if channel:
            filename = f"{channel.file_prefix}{self.session.get_filename_context()}.log"
            return self.session_dir / filename

        # Subtype channel? Format is "<base>-<subtype>" -- inherit base prefix.
        if "-" in channel_name:
            base_name, _, subtype = channel_name.partition("-")
            base_channel = self.config.routing.channels.get(base_name)
            if base_channel and subtype:
                base_prefix = base_channel.file_prefix.rstrip("_")
                derived_prefix = f"{base_prefix}-{subtype}_"
                filename = f"{derived_prefix}{self.session.get_filename_context()}.log"
                return self.session_dir / filename

        raise ValueError(f"Unknown channel: {channel_name}")

    def _maybe_write_session_marker(self) -> None:
        """Write session-start or compaction marker if this is first call of a new run.

        v0.3.7 Phase 4 (Github #39): broadcasts markers to every enabled channel
        whose ChannelOptions.suppress_markers is False. Run/compaction numbers
        are counted from the unified sesslog path (authoritative source), so
        subtype-derived channel proliferation doesn't affect run counts.
        Subtype-derived channels (`.bash-powershell_*`, etc.) deliberately
        receive no markers — they materialize lazily on first write and may
        not exist at marker time; keeping them clean is the documented policy.
        """
        if not is_new_session_run(self.session.session_id):
            return  # Already wrote marker for this run

        # Read source from state file (#14 - distinguish compaction from true start)
        source = None
        source_file = Path.home() / ".claude" / "session-states" / f"{self.session.session_id}.source"
        try:
            if source_file.exists():
                source = source_file.read_text().strip()
                source_file.unlink()  # Clean up after reading
        except Exception:
            pass  # Fall back to default marker

        # Determine the appropriate counter based on event type
        if source == "compact":
            # Count compaction markers separately (#14)
            marker_number = count_compaction_markers(self.unified_log_path) + 1
        else:
            # Run number only increments for true session starts
            marker_number = get_run_number(self.session.session_id, self.unified_log_path)

        # Broadcast to all enabled channels that don't suppress markers
        target_paths = self._collect_marker_target_paths()
        for path in target_paths:
            write_session_marker(path, marker_number, self.event_time, self.effective_name, source)

        # Mark session as started
        mark_session_started(self.session.session_id)

        debug_log(
            f"Wrote {'compaction' if source == 'compact' else 'session'} marker: "
            f"#{marker_number} to {len(target_paths)} channel(s)"
        )

    def _collect_marker_target_paths(self) -> list[Path]:
        """Resolve marker target paths for all enabled, non-suppressed channels.

        Only iterates top-level declared channels (`routing.channels`). Subtype
        derivatives like `.bash-powershell_*` are excluded by design — they
        appear lazily on first matching tool call, and we keep them clean.
        Unresolvable channels (path-resolution failure) are silently skipped.
        """
        paths: list[Path] = []
        for channel_name, channel in self.config.routing.channels.items():
            if not channel.enabled:
                continue
            if channel.options.suppress_markers:
                continue
            try:
                paths.append(self._get_channel_path(channel_name))
            except ValueError:
                continue  # Unresolvable channel — skip rather than crash
        return paths

    def _expand_with_subtype_channels(
        self,
        channels: list[str],
        tool_name: str,
        tool_category: str,
        raw_json: Optional[dict[str, Any]] = None
    ) -> list[str]:
        """Expand channel list with per-subtype channels per channel opt-in.

        v0.3.7-pre (supersedes #48): subtype splitting is decided per-channel
        via `ChannelOptions.subtype_split` rather than category-wide via the
        former `routing.subtype_routing` toggle. For each base channel, the
        channel's own options say whether to add a `<channel>-<subtype>`
        sibling for the current event:

          - subtype_split = False (default): no expansion for this channel
          - subtype_split = True            : expand for any subtype
          - subtype_split = ["help", "X"]   : expand only for listed subtypes

        Iterates the ORIGINAL channel list, NOT the expanded list -- this is
        the no-recursion guarantee. `.agents-help_*` never chains further to
        `.agents-help-bash_*` even if multiple categories have extractors.
        """
        if raw_json is None:
            return channels  # Cannot extract subtype without raw_json

        subtype = get_subtype(tool_category, tool_name, raw_json)
        if not subtype:
            return channels  # No meaningful subtype to attach

        expanded = list(channels)
        for base_channel in channels:  # iterate ORIGINAL list -- no recursion
            channel_obj = self.config.routing.channels.get(base_channel)
            opts = self._resolve_channel_options(channel_obj, base_channel)
            if opts is None:
                continue  # No options resolvable -- subtype_split is False by definition
            split = opts.subtype_split
            if not split:
                continue
            if isinstance(split, list) and subtype not in split:
                continue
            subtype_channel = f"{base_channel}-{subtype}"
            if subtype_channel not in expanded:
                expanded.append(subtype_channel)
        return expanded

    def log_entry(
        self,
        entry,  # str (transitional, conversation.py until Step 6) or LogEntry
        tool_name: str,
        tool_category: str,
        event_time: Optional[datetime] = None,
        raw_json: Optional[dict[str, Any]] = None,
    ) -> None:
        """Write entry to appropriate log files based on routing configuration.

        Phase 2+3 Step 5: the `task_content` parameter is gone — task-tool
        callers now stuff the task_content string into the LogEntry's
        metadata dict, and the `tasks` channel declares
        `formatter="task-only"` in its default ChannelOptions. The dispatch
        in `format_for_channel()` picks the right formatter automatically;
        no per-channel special cases here anymore.

        Args:
            entry: A LogEntry (handler-emitted, post-Step-4) or str
                (transitional shape from conversation.py until Step 6).
            tool_name: The name of the tool (for routing overrides)
            tool_category: The category of the tool (e.g., "task", "bash")
            event_time: The event timestamp (ensures consistency across channels)
            raw_json: Optional raw event payload (used for subtype extraction)
        """
        ts = event_time or datetime.now()

        # Get channels to write to based on routing config
        channels = self._get_channels_for_tool(tool_name, tool_category)
        # Expand with subtype channels (no-op if subtype routing not configured)
        channels = self._expand_with_subtype_channels(
            channels, tool_name, tool_category, raw_json
        )

        # Track time gaps per channel to avoid duplicate gap checks
        gap_cache: dict[Path, bool] = {}

        for channel_name in channels:
            # Check if channel is enabled
            channel = self.config.routing.channels.get(channel_name)
            if channel and not channel.enabled:
                continue

            try:
                file_path = self._get_channel_path(channel_name)
            except ValueError:
                debug_log(f"Skipping unknown channel: {channel_name}")
                continue

            # Check for time gap (cache to avoid repeated checks)
            if file_path not in gap_cache:
                gap_cache[file_path] = check_time_gap(file_path, self.config.datetime_mode, ts)
            add_gap = gap_cache[file_path]

            # Resolve channel options. For subtype-derived channels
            # (e.g., "shell-powershell" from subtype_routing) that aren't
            # explicitly declared in routing.channels, inherit the base
            # channel's options ("shell" in this case). Standard
            # inheritance pattern: declare-to-override, omit-to-inherit.
            channel_opts = self._resolve_channel_options(channel, channel_name)

            # Route through formatter dispatch. For str entries (still
            # emitted by conversation.py until Step 6), DefaultFormatter
            # passes through. For LogEntry entries (handler-emitted), the
            # selected formatter handles assembly per channel options —
            # including the task-only formatter on the `tasks` channel.
            formatted = format_for_channel(
                entry, channel_opts, channel_name, self.config
            )
            atomic_append(file_path, formatted, add_gap=add_gap)

    def _resolve_channel_options(self, channel, channel_name: str):
        """Return ChannelOptions for `channel_name`, inheriting base if needed.

        Subtype-derived channel names follow the `<base>-<subtype>` shape
        (e.g., "shell-powershell", "tools-github") and aren't explicitly
        declared in routing.channels — they're manufactured at log time when
        subtype_routing is enabled. Without inheritance, these channels
        would silently fall back to global defaults, losing the parent
        channel's customization (e.g., `tools` channel's max_chars=100 would
        not apply to `.tools-github_*.log`).

        Resolution order:
          1. If `channel` is explicitly declared (and we have it), use its options
             (declare-to-override path)
          2. Else if `channel_name` has the `<base>-<subtype>` shape, look up
             the base channel and inherit its options (omit-to-inherit path)
          3. Else None (global defaults)
        """
        if channel is not None:
            return channel.options
        if "-" in channel_name:
            base_name = channel_name.partition("-")[0]
            base_channel = self.config.routing.channels.get(base_name)
            if base_channel is not None:
                return base_channel.options
        return None

    def log_failure(self, failure_entry: str) -> None:
        """Log a failure entry to history files."""
        atomic_append(self.shell_log_path, failure_entry)
        atomic_append(self.unified_log_path, failure_entry)
