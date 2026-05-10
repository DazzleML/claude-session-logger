"""Bash failure detection: find pre-captured command data + error indicators.

When `failure_capture_enabled` is set, examines `CLAUDE_TOOL_OUTPUT` for
common shell error patterns and emits a `[FAILED: reason]` annotation
alongside the original entry. Reads pre-capture sidecar files in
`~/.claude/captures/` so the failure entry can show the exact bash
command and cwd, even when the hook only sees post-execution context.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from cclogger.formatters import format_datetime, should_use_action_only
from cclogger.logger import SessionLogger
from cclogger.models import Config, ToolInfo


# ============================================================================
# Failure Detection
# ============================================================================


def detect_and_log_failure(
    tool_info: ToolInfo, config: Config, logger: SessionLogger, event_time: datetime
) -> None:
    """Enhanced failure detection for Bash commands.

    Args:
        tool_info: Information about the tool call
        config: Logger configuration
        logger: The session logger instance
        event_time: The event timestamp (for consistent timestamps with main entry)
    """
    if tool_info.name != "Bash" or not config.failure_capture_enabled:
        return

    # Look for pre-captured command data
    capture_dir = Path.home() / ".claude" / "captures"
    capture_file = None

    if capture_dir.exists():
        # Find most recent capture file for this session (within last 5 minutes)
        import time

        cutoff_time = time.time() - 300  # 5 minutes ago

        for f in capture_dir.glob(f"{tool_info.session_id}-*"):
            if f.stat().st_mtime > cutoff_time:
                capture_file = f
                break

    # Determine command source and details
    bash_command = ""
    command_cwd = ""

    if capture_file and capture_file.exists():
        try:
            with open(capture_file, "r", encoding="utf-8") as f:
                capture_data = json.load(f)
                bash_command = capture_data.get("bash_command", "")
                command_cwd = capture_data.get("cwd", "")
            capture_file.unlink(missing_ok=True)
        except Exception:
            pass
    else:
        bash_command = tool_info.input.get("command", "")
        command_cwd = os.getcwd()

    # Check for failure indicators
    failure_detected = False
    failure_reason = ""
    error_output = ""

    tool_output = os.environ.get("CLAUDE_TOOL_OUTPUT", "")
    if tool_output:
        error_patterns = [
            "command not found",
            "No such file or directory",
            "Permission denied",
            "syntax error",
            "Failed to execute",
            "exit status",
        ]
        for pattern in error_patterns:
            if pattern in tool_output:
                failure_detected = True
                failure_reason = "error detected in output"
                error_output = tool_output
                break

    if failure_detected:
        # Generate failure entry (use same event_time as main entry)
        datetime_part = format_datetime(config.datetime_mode, event_time)

        pwd_part = ""
        if config.pwd_enabled:
            pwd_part = f' ["{command_cwd or os.getcwd()}"]'

        if should_use_action_only(tool_info.name, config):
            failure_content = "Bash"
        elif config.verbosity <= 1:
            failure_content = bash_command
        else:
            failure_content = f"Bash: {bash_command}"

        failure_entry = f"{datetime_part}{{{failure_content} }} [FAILED: {failure_reason}]{pwd_part}"

        # Add error output if enabled
        if config.failure_capture_stderr and error_output:
            lines = error_output.split("\n")[: config.failure_capture_max_lines]
            formatted_error = "\n".join(f"  {line}" for line in lines)
            if formatted_error:
                failure_entry += "\n" + formatted_error

        logger.log_failure(failure_entry)

    # Cleanup old capture files
    if capture_dir.exists():
        import time

        cutoff_time = time.time() - 600  # 10 minutes ago
        for f in capture_dir.glob(f"{tool_info.session_id}-*"):
            try:
                if f.stat().st_mtime < cutoff_time:
                    f.unlink()
            except Exception:
                pass
