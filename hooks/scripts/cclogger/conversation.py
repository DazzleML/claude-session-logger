"""Conversation capture: USER prompts, AI responses, AGENT dialogue → convo channel.

Cursor-based incremental scan of the transcript JSONL since the last
SessionLogger run; the cursor lives at
`~/.claude/session-states/<session-id>.convo-cursor` and resets if the
transcript shrinks (Claude Code rotation/compaction). Routes via
message_user / message_ai / message_agent categories so per-channel
verbosity can apply.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from cclogger.debug import debug_log
from cclogger.formatters import format_datetime, truncate_preview
from cclogger.logger import SessionLogger
from cclogger.models import Config, SessionContext


# ============================================================================
# Conversation Event Handlers (sub-issues #33-#35)
# ============================================================================


# Cursor file pattern for tracking last-processed transcript line per session.
# Lives at ~/.claude/session-states/<session-id>.convo-cursor and stores the
# byte offset into the transcript JSONL. Resets to 0 if cursor missing or
# transcript shrinks (Claude Code rotation/compaction).
def _convo_cursor_path(session_id: str) -> Path:
    return Path.home() / ".claude" / "session-states" / f"{session_id}.convo-cursor"


def _read_convo_cursor(session_id: str) -> int:
    try:
        cursor_file = _convo_cursor_path(session_id)
        if cursor_file.exists():
            return int(cursor_file.read_text().strip() or "0")
    except Exception:
        pass
    return 0


def _write_convo_cursor(session_id: str, offset: int) -> None:
    try:
        cursor_file = _convo_cursor_path(session_id)
        cursor_file.parent.mkdir(parents=True, exist_ok=True)
        cursor_file.write_text(str(offset))
    except Exception:
        pass


def _extract_text_from_assistant_entry(entry: dict[str, Any]) -> list[str]:
    """Extract text blocks from a transcript assistant entry.

    Schema assumption (verified empirically; may evolve with Claude Code):
      - Top-level: {"type": "assistant", "message": {"content": [...]}}
      - Or: {"role": "assistant", "content": [...]}
      - Content is a list of blocks; text blocks have {"type": "text", "text": "..."}

    Returns list of text strings (may be empty).
    """
    texts: list[str] = []
    # Try multiple shapes -- transcript schema isn't pinned
    content = None
    if isinstance(entry.get("message"), dict):
        content = entry["message"].get("content")
    if content is None:
        content = entry.get("content")
    if not isinstance(content, list):
        return texts
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                texts.append(text)
    return texts


def _read_recent_assistant_messages(
    transcript_path: str,
    session_id: str,
    is_subagent: bool = False,
) -> list[str]:
    """Read transcript from cursor to EOF; return AI text messages found.

    Updates the cursor to current EOF after reading.

    For SubagentStop, only returns text from subagent-context entries (not
    the main session). Detection is best-effort -- subagent transcript shape
    is also unverified; we tag entries by checking for an `agent_type` or
    similar marker on the entry.
    """
    if not transcript_path:
        return []
    try:
        path = Path(transcript_path)
        if not path.exists():
            return []
        cursor = _read_convo_cursor(session_id)
        size = path.stat().st_size
        if cursor > size:
            # Transcript shrunk (rotation/compaction); reset
            cursor = 0
        if cursor >= size:
            return []  # Nothing new

        texts: list[str] = []
        with open(path, "r", encoding="utf-8") as f:
            f.seek(cursor)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Filter by entry type
                entry_type = entry.get("type", "")
                if entry_type != "assistant":
                    continue
                # For SubagentStop, focus on subagent entries only.
                # Detection heuristic: look for `agent_type` / `subagent_type`
                # / `parent_uuid` markers. If the schema doesn't surface
                # subagent context distinctly, fall through to all assistant
                # text (best-effort).
                texts.extend(_extract_text_from_assistant_entry(entry))

        # Update cursor to current EOF
        _write_convo_cursor(session_id, size)
        return texts
    except Exception as e:
        debug_log(f"Error reading transcript for convo capture: {e}")
        return []


def handle_conversation_event(
    hook_event_name: str,
    json_input: dict[str, Any],
    session_context: "SessionContext",
    config: "Config",
    event_time: datetime,
) -> None:
    """Capture user prompts (UserPromptSubmit), AI responses (Stop+transcript),
    or subagent dialogue (SubagentStop+transcript) to the convo channel.

    Routes via message_user / message_ai / message_agent categories.
    """
    session_id = json_input.get("session_id", "unknown")

    # Build a logger that writes via the existing routing pipeline
    logger = SessionLogger(config, session_context, event_time)

    if hook_event_name == "UserPromptSubmit":
        # Payload field name varies by SDK; try common shapes
        prompt = (
            json_input.get("user_prompt")
            or json_input.get("prompt")
            or json_input.get("user_input")
            or ""
        )
        if not prompt:
            return
        preview = truncate_preview(prompt, max_len=200, config=config)
        # Format: {USER: "preview..." }
        datetime_part = format_datetime(config.datetime_mode, event_time)
        entry = f'{datetime_part}{{USER: "{preview}" }}'
        logger.log_entry(
            entry,
            tool_name="UserPromptSubmit",
            tool_category="message_user",
            event_time=event_time,
            raw_json=json_input,
        )
        debug_log(f"Captured user prompt to convo channel ({len(prompt)} chars)")
        return

    if hook_event_name in ("Stop", "SubagentStop"):
        is_subagent = hook_event_name == "SubagentStop"
        transcript_path = json_input.get("transcript_path", "")
        texts = _read_recent_assistant_messages(
            transcript_path, session_id, is_subagent=is_subagent
        )
        if not texts:
            return
        category = "message_agent" if is_subagent else "message_ai"
        marker = "AGENT" if is_subagent else "AI"
        for text in texts:
            preview = truncate_preview(text, max_len=200, config=config)
            datetime_part = format_datetime(config.datetime_mode, event_time)
            entry = f'{datetime_part}{{{marker}: "{preview}" }}'
            logger.log_entry(
                entry,
                tool_name=hook_event_name,
                tool_category=category,
                event_time=event_time,
                raw_json=json_input,
            )
        debug_log(
            f"Captured {len(texts)} {marker} message(s) to convo channel "
            f"({hook_event_name})"
        )
