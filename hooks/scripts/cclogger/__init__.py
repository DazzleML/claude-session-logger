"""cclogger — modular implementation of the claude-session-logger hook.

Loaded by `hooks/scripts/log-command.py` (the entry point) after a
`sys.path.insert` makes this directory importable. Importing any
`cclogger.X` module triggers this `__init__` first, which calls
`_ensure_dazzle_filekit()` so subsequent module-level
`from dazzle_filekit import ...` statements succeed.

The re-exports below are a compatibility shim for tests that import
the package itself via `importlib.import_module("cclogger")` and look
up symbols by attribute access. New code should import directly from
the home module (e.g. `from cclogger.conversation import _convo_cursor_path`).
Per Phase 0b, monkeypatches in tests target the home module string
form (`"cclogger.conversation._convo_cursor_path"`) -- patching this
namespace would not intercept lookups inside other cclogger modules.
"""

from cclogger.debug import _ensure_dazzle_filekit

# Auto-install dazzle-filekit before any cclogger module attempts
# `from dazzle_filekit import ...` at import time. Idempotent: returns
# immediately if dazzle_filekit is already importable.
_ensure_dazzle_filekit()

# --- Re-exports for backwards-compatible test access --------------------------

from cclogger.categorize import (
    SUBTYPE_EXTRACTORS,
    categorize_tool,
    get_subtype,
)
from cclogger.config import ConfigLoader
from cclogger.conversation import (
    _convo_cursor_path,
    _extract_text_from_assistant_entry,
    _read_convo_cursor,
    _read_recent_assistant_messages,
    _write_convo_cursor,
)
from cclogger.debug import (
    UNKNOWN_TOOL_WARN_DIR,
    _warn_unknown_tool_once,
    debug_log,
)
from cclogger.formatters import generate_entry, get_command_content, truncate_preview
from cclogger.logger import SessionLogger
from cclogger.models import (
    ChannelConfig,
    Config,
    LogEntry,
    PerformanceConfig,
    RoutingConfig,
    SessionContext,
    ToolInfo,
    _default_category_routes,
    _default_channels,
)
from cclogger.reconciliation import (
    _rename_files_for_session_change,
    build_session_directory,
)
from cclogger.session_naming import sanitize_dirname
from cclogger.session_state import build_session_context

__all__ = [
    "ChannelConfig",
    "Config",
    "ConfigLoader",
    "LogEntry",
    "PerformanceConfig",
    "RoutingConfig",
    "SUBTYPE_EXTRACTORS",
    "SessionContext",
    "SessionLogger",
    "ToolInfo",
    "UNKNOWN_TOOL_WARN_DIR",
    "_convo_cursor_path",
    "_default_category_routes",
    "_default_channels",
    "_ensure_dazzle_filekit",
    "_extract_text_from_assistant_entry",
    "_read_convo_cursor",
    "_read_recent_assistant_messages",
    "_rename_files_for_session_change",
    "_warn_unknown_tool_once",
    "_write_convo_cursor",
    "build_session_context",
    "build_session_directory",
    "categorize_tool",
    "debug_log",
    "generate_entry",
    "get_command_content",
    "get_subtype",
    "sanitize_dirname",
    "truncate_preview",
]
