#!/usr/bin/env python3
"""Claude Code session command history logger.

Orthogonal control: Verbosity (0-4) + Context flags (datetime/pwd) + Tool filtering

Format examples:
  Level 0: {command}
  Level 1: {optional_datetime}{command}{optional_pwd}
  Level 2: {optional_datetime}{tool command}{optional_pwd}
  Level 3: {optional_datetime}{tool command description}{optional_pwd}
  Level 4: {optional_datetime}{tool command full_json}{optional_pwd}

After v0.3.7 modularization (#37), the implementation lives in the
sibling `cclogger/` package. This file is the hook entry point: read
JSON from stdin, dispatch on hook_event_name, and call the right
cclogger functions to do the work.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Phase 0a bootstrap: make hooks/scripts/ importable so `from cclogger.X import Y`
# resolves once Phase 0b moves code into the cclogger/ package. Safe no-op while
# the package is still empty.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cclogger.categorize import categorize_tool
from cclogger.config import load_configuration
from cclogger.conversation import handle_conversation_event
from cclogger.debug import DEBUG_LOG, _warn_unknown_tool_once, debug_log
from cclogger.failure_detection import detect_and_log_failure
from cclogger.formatters import (
    generate_entry,
    get_command_content_structured,
    get_task_content,
    should_log_tool,
)
from cclogger.logger import SessionLogger
from cclogger.models import ToolInfo
from cclogger.reconciliation import reconcile_session_directory
from cclogger.session_naming import apply_auto_name_on_session_start
from cclogger.session_state import (
    build_session_context,
    ensure_transcript_symlink,
    write_session_state,
)


# ============================================================================
# Main Entry Point
# ============================================================================


def main() -> None:
    """Entry point for Claude Code hook."""
    # Capture event time ONCE at the earliest point - ensures all channels
    # get identical timestamps for the same event
    event_time = datetime.now()

    debug_log("Hook started (Python)")
    debug_log(f"JSON keys will be logged after parse")

    # Read JSON input from stdin (explicitly decode as UTF-8 for Windows compatibility)
    # On Windows, sys.stdin defaults to CP1252, but Claude sends UTF-8
    try:
        raw_input = sys.stdin.buffer.read().decode('utf-8')
        json_input = json.loads(raw_input)
    except json.JSONDecodeError as e:
        debug_log(f"JSON parse error: {e}")
        print('{"continue": true}')
        return

    debug_log(f"JSON_INPUT length: {len(str(json_input))}")
    debug_log(f"JSON keys: {list(json_input.keys())}")

    # Log additional details to help investigate agent context (#5)
    # These will help us understand what fields are available
    for key in ["subagent_type", "agent_type", "agent_context", "parent_agent",
                "spawned_by", "agent", "tool_params"]:
        if key in json_input:
            debug_log(f"Agent investigation - {key}: {json_input[key]}")

    # Detect hook event type
    hook_event_name = json_input.get("hook_event_name", "PostToolUse")
    debug_log(f"Hook event: {hook_event_name}")

    # Log source field for SessionStart events to investigate compaction detection (#14)
    if hook_event_name == "SessionStart":
        source = json_input.get("source", "unknown")
        model = json_input.get("model", "unknown")
        debug_log(f"SessionStart source: {source}, model: {model}")

    # Parse tool info
    tool_info = ToolInfo.from_json(json_input)

    # On SessionStart, apply auto-naming from folder if session is unnamed
    # This stores the name in cache BEFORE build_session_context reads it
    auto_name = apply_auto_name_on_session_start(
        session_id=tool_info.session_id,
        transcript_path=tool_info.transcript_path,
        cwd=json_input.get("cwd", ""),
        hook_event_name=hook_event_name
    )
    if auto_name:
        debug_log(f"Auto-named session from folder: {auto_name}")

    # On SessionStart, clear state flags so the next PostToolUse
    # writes a fresh SESSION START marker with correct run number
    # (fixes #9 - session resume detection)
    if hook_event_name == "SessionStart":
        state_dir = Path.home() / ".claude" / "session-states"
        state_dir.mkdir(parents=True, exist_ok=True)
        source = json_input.get("source", "unknown")
        # Clear .started flag so marker gets written
        started_flag = state_dir / f"{tool_info.session_id}.started"
        # Save source for marker text (#14 - distinguish compaction from true start)
        source_file = state_dir / f"{tool_info.session_id}.source"
        try:
            started_flag.unlink(missing_ok=True)
            # Only clear .run cache for true session starts, not compactions (#14)
            if source != "compact":
                run_cache = state_dir / f"{tool_info.session_id}.run"
                run_cache.unlink(missing_ok=True)
                debug_log(f"Cleared .started/.run flags, saved source={source}")
            else:
                debug_log(f"Cleared .started flag (compaction, .run preserved), saved source={source}")
            # Write source value for next PostToolUse to read
            source_file.write_text(source)
        except Exception as e:
            debug_log(f"Could not update session flags: {e}")

    # Build session context
    session_context = build_session_context(tool_info)
    context_string = session_context.get_filename_context()

    # Load configuration
    config = load_configuration(context_string)

    # For non-tool hooks (SessionStart, Stop), we still need to update state
    # and potentially trigger session directory reconciliation
    is_tool_hook = hook_event_name in ("PostToolUse", "PreToolUse", "PostToolUseFailure")

    # Create sesslog directory structure (needed for state file)
    sesslog_base = Path.home() / ".claude" / "sesslogs"
    sesslog_base.mkdir(parents=True, exist_ok=True)

    # Get or create session directory
    # This handles renames if session name changed (e.g., after /rename)
    session_dir, _ = reconcile_session_directory(
        sesslog_base,
        tool_info.session_id,
        session_context.session_name,
        session_context.username
    )

    # Write session state file (enables commands like /renameAI to access context)
    write_session_state(
        session_id=tool_info.session_id,
        transcript_path=tool_info.transcript_path,
        cwd=json_input.get("cwd", ""),
        sesslog_dir=session_dir,
        current_name=session_context.session_name,
    )

    # Create transcript symlink in sesslog directory (non-blocking on failure)
    ensure_transcript_symlink(session_dir, tool_info.transcript_path)

    # Conversation events (sub-issues #33-#35): UserPromptSubmit, Stop,
    # SubagentStop -- capture user/AI/agent prose to the convo channel
    # before the non-tool early-exit below.
    if hook_event_name in ("UserPromptSubmit", "Stop", "SubagentStop"):
        try:
            handle_conversation_event(
                hook_event_name=hook_event_name,
                json_input=json_input,
                session_context=session_context,
                config=config,
                event_time=event_time,
            )
        except Exception as e:
            debug_log(f"Conversation event handler error ({hook_event_name}): {e}")

    # For non-tool hooks, we're done after updating state
    if not is_tool_hook:
        debug_log(f"Non-tool hook ({hook_event_name}), state updated, exiting")
        print('{"continue": true}')
        return

    # Check if tool should be logged
    if not should_log_tool(tool_info.name, config):
        print('{"continue": true}')
        return

    # Extract command content (Phase 2+3 Step 7: structured form so handlers
    # can carry rich-format templates with `{snippet}` placeholders for
    # per-channel verbosity).
    command_content = get_command_content_structured(tool_info, config)

    # If extraction returned nothing despite input being present, the tool
    # likely has no specific handler AND its fields don't match the generic
    # fallback list. Warn once per tool_name (across all hook invocations,
    # via sentinel file) so we can add a proper handler without spamming the
    # debug log on every call.
    if not command_content.legacy_string and tool_info.input:
        _warn_unknown_tool_once(tool_info.name, list(tool_info.input.keys()))

    # Generate entry (using captured event_time for consistency)
    entry = generate_entry(tool_info, config, command_content, event_time)

    # Get task content if applicable. Phase 2+3 Step 5 stuffs this into the
    # LogEntry's metadata so the `task-only` formatter can find it without
    # log_entry() needing a special-case parameter.
    tool_category = categorize_tool(tool_info.name)
    if tool_category == "task":
        entry.metadata["task_content"] = get_task_content(
            tool_info.name, tool_info.raw_json, config
        )
        entry.metadata["raw_json"] = tool_info.raw_json

    # Create logger and write entry (pass event_time for channel consistency)
    # SessionLogger handles file reconciliation and session markers on init
    logger = SessionLogger(config, session_context, event_time)
    logger.log_entry(entry, tool_info.name, tool_category, event_time=event_time, raw_json=tool_info.raw_json)

    # Check for failures (Bash only, uses same event_time)
    detect_and_log_failure(tool_info, config, logger, event_time)

    debug_log(f"Logged to {logger.shell_log_path}")

    # Return success
    print('{"continue": true}')


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never block Claude Code -- log the error and continue
        try:
            DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(DEBUG_LOG, "a") as f:
                f.write(f"{datetime.now()}: FATAL unhandled exception: {e}\n")
        except Exception:
            pass
        print('{"continue": true}')
