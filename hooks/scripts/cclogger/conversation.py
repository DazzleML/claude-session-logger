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
from typing import Any, Optional

from cclogger import paths
from cclogger.debug import debug_log
from cclogger.logger import SessionLogger
from cclogger.models import Config, LogEntry, SessionContext


# ============================================================================
# Conversation Event Handlers (sub-issues #33-#35)
# ============================================================================


# Cursor file pattern for tracking last-processed transcript line per session.
# Lives at ~/.claude/session-states/<session-id>.convo-cursor and stores the
# byte offset into the transcript JSONL. Resets to 0 if cursor missing or
# transcript shrinks (Claude Code rotation/compaction).
def _convo_cursor_path(session_id: str) -> Path:
    return paths.session_states() / f"{session_id}.convo-cursor"


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


# ----------------------------------------------------------------------------
# Sidechain capture (sidechain-capture design, 2026-09-03, unit 2)
#
# Claude Code keeps each subagent's turns in its own transcript
# (`~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl`) and
# hands its path to the SubagentStop hook as `agent_transcript_path`. The
# main transcript never contains an agent's turns (0 `isSidechain` entries
# in 3,352 measured), so the old SubagentStop read of the MAIN transcript
# from the cursor shared with Stop could only ever return main-thread
# narration -- which it then labeled as the agent's report while the agent's
# own report was dropped (the report-leg bug). The reader below reads the
# agent's file instead, through a cursor keyed by agent id so a resumed
# agent (SendMessage) yields each turn once.
# ----------------------------------------------------------------------------

def _agent_cursor_path(session_id: str, agent_id: str) -> Path:
    safe = "".join(ch for ch in str(agent_id) if ch.isalnum() or ch in "-_")
    return paths.session_states() / f"{session_id}.agent-{safe}.cursor"


def _read_agent_cursor(session_id: str, agent_id: str) -> int:
    try:
        p = _agent_cursor_path(session_id, agent_id)
        if p.exists():
            return int(p.read_text().strip() or "0")
    except Exception:
        pass
    return 0


def _write_agent_cursor(session_id: str, agent_id: str, offset: int) -> None:
    try:
        p = _agent_cursor_path(session_id, agent_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(offset))
    except Exception:
        pass


def _extract_blocks_from_assistant_entry(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the entry's narrative blocks in order as (kind, text) pairs:
    ("text", ...) for text blocks and ("thinking", ...) for thinking blocks
    (`{"type": "thinking", "thinking": "...", "signature": ...}`; the
    signature is never recorded). tool_use / tool_result blocks are skipped:
    an agent's tool calls are already logged live by PostToolUse inside
    the agent, and reading them again would double every call."""
    blocks: list[tuple[str, str]] = []
    content = None
    if isinstance(entry.get("message"), dict):
        content = entry["message"].get("content")
    if content is None:
        content = entry.get("content")
    if not isinstance(content, list):
        return blocks
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                blocks.append(("text", text))
        elif btype == "thinking":
            text = block.get("thinking", "")
            if isinstance(text, str) and text.strip():
                blocks.append(("thinking", text))
    return blocks


def _entry_timestamp(entry: dict[str, Any]) -> Optional[datetime]:
    """The transcript entry's own time as a local naive datetime (the log's
    stamps are local time), or None when absent or unparseable."""
    raw = entry.get("timestamp")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _read_sidechain(
    transcript_path: str,
    session_id: str,
    agent_id: str,
    include_thinking: bool = True,
) -> list[tuple[str, str, Optional[datetime]]]:
    """Read an agent's sidechain transcript from this agent's cursor to EOF
    and return its narrative as (kind, text, entry_time) triples in order --
    text and, when `include_thinking`, thinking; never tool blocks. Updates
    the per-agent cursor; resets it if the file shrank. A missing or empty
    path yields [] silently (Claude Code's untyped forks have no sidechain:
    0 of 709 transcripts on the dev box)."""
    if not transcript_path or not agent_id:
        return []
    try:
        path = Path(transcript_path)
        if not path.exists():
            return []
        cursor = _read_agent_cursor(session_id, agent_id)
        size = path.stat().st_size
        if cursor > size:
            cursor = 0
        if cursor >= size:
            return []
        items: list[tuple[str, str, Optional[datetime]]] = []
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
                if entry.get("type") != "assistant":
                    continue
                when = _entry_timestamp(entry)
                for kind, text in _extract_blocks_from_assistant_entry(entry):
                    if kind == "thinking" and not include_thinking:
                        continue
                    items.append((kind, text, when))
        _write_agent_cursor(session_id, agent_id, size)
        return items
    except Exception as e:
        debug_log(f"Error reading sidechain transcript for agent {agent_id}: {e}")
        return []


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


def _read_recent_assistant_blocks(
    transcript_path: str,
    session_id: str,
    include_thinking: bool = True,
) -> list[tuple[str, str]]:
    """Read the MAIN transcript from the session's convo cursor to EOF and
    return the assistant's narrative blocks in order as (kind, text) pairs
    -- text and, when `include_thinking`, thinking (sidechain-capture unit
    3, 2026-09-03: this session's own transcript held 293 thinking blocks
    against 78 text blocks, all previously dropped). Tool blocks are never
    returned (PostToolUse logs them live). Updates the cursor to EOF;
    resets it if the transcript shrank (rotation / compaction). Only the
    Stop handler reads this file: SubagentStop reads the agent's own
    sidechain and never touches this cursor.
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

        blocks: list[tuple[str, str]] = []
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
                if entry.get("type", "") != "assistant":
                    continue
                for kind, text in _extract_blocks_from_assistant_entry(entry):
                    if kind == "thinking" and not include_thinking:
                        continue
                    blocks.append((kind, text))

        # Update cursor to current EOF
        _write_convo_cursor(session_id, size)
        return blocks
    except Exception as e:
        debug_log(f"Error reading transcript for convo capture: {e}")
        return []


def _read_recent_assistant_messages(
    transcript_path: str,
    session_id: str,
    is_subagent: bool = False,
) -> list[str]:
    """Text-only view of `_read_recent_assistant_blocks` (kept for callers and
    tests that want narration alone). `is_subagent` is accepted for
    compatibility and ignored: SubagentStop no longer reads this file."""
    return [text for _kind, text in
            _read_recent_assistant_blocks(transcript_path, session_id, include_thinking=False)]


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
        # Phase 2+3 Step 6: emit LogEntry with raw_content; per-channel
        # formatter dispatch handles truncation. The v0.3.6 hardcoded
        # `truncate_preview(prompt, max_len=200)` is gone — convo channel
        # default is verbosity="full" + formatter="chat" + RENDER newlines;
        # other channels (sesslog) format per their own ChannelOptions.
        entry = LogEntry(
            raw_content=prompt,
            role="user",
            tool_name="UserPromptSubmit",
            timestamp=event_time,
        )
        logger.log_entry(
            entry,
            tool_name="UserPromptSubmit",
            tool_category="message_user",
            event_time=event_time,
            raw_json=json_input,
        )
        debug_log(f"Captured user prompt to convo channel ({len(prompt)} chars)")
        return

    if hook_event_name == "SubagentStart":
        _handle_subagent_start(json_input, session_id, logger, config, event_time)
        return

    if hook_event_name == "SubagentStop":
        _handle_subagent_stop(json_input, session_id, logger, config, event_time)
        return

    if hook_event_name == "Stop":
        # Main-thread narration AND thinking (unit 3), in block order, under
        # the global switch. Thinking entries carry kind="thinking" and
        # display as {THINK: ...}; channels opt out per
        # ChannelOptions.thinking / exclude {"kind": ["thinking"]}.
        from cclogger.models import KIND_THINKING
        transcript_path = json_input.get("transcript_path", "")
        blocks = _read_recent_assistant_blocks(
            transcript_path, session_id,
            include_thinking=bool(getattr(config, "thinking", True)),
        )
        if not blocks:
            return
        for kind, text in blocks:
            entry = LogEntry(
                raw_content=text,
                role="ai",
                tool_name=hook_event_name,
                timestamp=event_time,
                kind=KIND_THINKING if kind == "thinking" else "text",
            )
            logger.log_entry(
                entry,
                tool_name=hook_event_name,
                tool_category="message_ai",
                event_time=event_time,
                raw_json=json_input,
            )
        n_think = sum(1 for k, _ in blocks if k == "thinking")
        debug_log(
            f"Captured {len(blocks) - n_think} AI message(s) and {n_think} thinking "
            f"block(s) to convo channel (Stop)"
        )


_START_DESCRIPTION_KEYS = ("description", "agent_description", "prompt", "task", "purpose")


def _handle_subagent_start(
    json_input: dict[str, Any],
    session_id: str,
    logger: SessionLogger,
    config: "Config",
    event_time: datetime,
) -> None:
    """SubagentStart (2026-09-03, unit 5): the kickoff line that opens a typed
    agent's block -- `{AGENT-START:explore: <description> }` -- carried as
    leg "dispatch" so it survives sesslog-main's exclusion of internal
    legs. The documented payload is `agent_id` + `agent_type`; a
    description-like field is used when one is present (the live shape is
    recorded by the debug log's key listing and checked by the release
    checklist). Untyped forks get no bracket: their whole story is one
    line (maintainer decision, Addendum 6)."""
    from cclogger.models import (AGENT_LEG_DISPATCH, UNTYPED_AGENT_CLASSIFIER,
                                 resolve_agent_identity)

    agent_ctx, agent_id = resolve_agent_identity(json_input)
    if not agent_id or agent_ctx == UNTYPED_AGENT_CLASSIFIER:
        return
    description = ""
    for key in _START_DESCRIPTION_KEYS:
        value = json_input.get(key)
        if isinstance(value, str) and value.strip():
            description = value.strip().splitlines()[0]
            break
    entry = LogEntry(
        raw_content=description or "started",
        role="agent-start",
        tool_name="SubagentStart",
        timestamp=event_time,
        agent_context=agent_ctx,
        agent_id=agent_id,
        agent_leg=AGENT_LEG_DISPATCH,
    )
    logger.log_entry(entry, tool_name="SubagentStart", tool_category="message_agent",
                     event_time=event_time, raw_json=json_input)
    debug_log(f"Captured AGENT-START for {agent_ctx}/{agent_id}")


def _handle_subagent_stop(
    json_input: dict[str, Any],
    session_id: str,
    logger: SessionLogger,
    config: "Config",
    event_time: datetime,
) -> None:
    """SubagentStop (2026-09-03, sidechain-capture unit 2).

    Identity via the ONE shared resolver (models.resolve_agent_identity):
    agent_id-gated; an empty agent_type is the bounded "untyped" classifier
    with the id kept on the entry (2026-09-02 incident).

    The agent's story comes from ITS OWN transcript (`agent_transcript_path`),
    read from a per-agent cursor: narration and thinking become internal-leg
    entries stamped with their own times; the final text is the report leg
    when it matches `last_assistant_message`. The main transcript is never
    read here -- it holds no agent turns, and reading it from the cursor
    shared with Stop is what labeled main-thread narration as an agent's
    report (the report-leg bug). Untyped forks have no sidechain, so they
    keep producing exactly the one payload line they produced before, with
    no warning.
    """
    from cclogger.models import (AGENT_LEG_INTERNAL, AGENT_LEG_REPORT, KIND_THINKING,
                                 resolve_agent_identity)

    agent_ctx, agent_id = resolve_agent_identity(json_input)
    if not agent_id:
        return  # not a subagent stop (defensive: the event should always carry an id)

    include_thinking = bool(getattr(config, "thinking", True))
    items = _read_sidechain(
        json_input.get("agent_transcript_path", ""), session_id, agent_id,
        include_thinking=include_thinking,
    )
    last = json_input.get("last_assistant_message")
    last_text = str(last).strip() if last else ""

    # Split the sidechain into internal legs and the report leg.
    report: Optional[tuple[str, Optional[datetime]]] = None
    internal = items
    text_items = [i for i, (kind, _t, _w) in enumerate(items) if kind == "text"]
    if text_items:
        last_i = text_items[-1]
        final_text = items[last_i][1]
        if not last_text or final_text.strip() == last_text:
            report = (final_text, items[last_i][2])
            internal = items[:last_i] + items[last_i + 1:]
        else:
            # AC-2 self-check: the file's last text should be the payload's
            # report. If it is not (a race with the agent's last write, or a
            # trimmed payload), keep everything the file holds as internal
            # legs and trust the payload for the report -- nothing is lost.
            debug_log(
                f"SIDECHAIN-MISMATCH agent={agent_id} type={agent_ctx}: the sidechain's "
                f"last text ({len(final_text)} chars) differs from last_assistant_message "
                f"({len(last_text)} chars); using the payload as the report"
            )
    if report is None and last_text:
        report = (str(last), None)

    emitted = 0
    for kind, text, when in internal:
        entry = LogEntry(
            raw_content=text,
            role="agent",
            tool_name="SubagentStop",
            timestamp=when or event_time,
            agent_context=agent_ctx,
            agent_id=agent_id,
            kind=KIND_THINKING if kind == "thinking" else "text",
            agent_leg=AGENT_LEG_INTERNAL,
        )
        logger.log_entry(entry, tool_name="SubagentStop", tool_category="message_agent",
                         event_time=event_time, raw_json=json_input)
        emitted += 1
    if report is not None:
        text, when = report
        entry = LogEntry(
            raw_content=text,
            role="agent",
            tool_name="SubagentStop",
            timestamp=when or event_time,
            agent_context=agent_ctx,
            agent_id=agent_id,
            agent_leg=AGENT_LEG_REPORT,
        )
        logger.log_entry(entry, tool_name="SubagentStop", tool_category="message_agent",
                         event_time=event_time, raw_json=json_input)
        emitted += 1
    # Close the block (unit 5): typed agents only, leg "report" so the
    # bracket survives sesslog-main; the untyped forks keep their one line.
    from cclogger.models import UNTYPED_AGENT_CLASSIFIER
    if agent_ctx != UNTYPED_AGENT_CLASSIFIER:
        n_think = sum(1 for kind, _t, _w in internal if kind == "thinking")
        summary = (
            f"stopped ({len(internal) - n_think} narration, {n_think} thinking, "
            f"{'report' if report is not None else 'no report'})"
        )
        entry = LogEntry(
            raw_content=summary,
            role="agent-stop",
            tool_name="SubagentStop",
            timestamp=event_time,
            agent_context=agent_ctx,
            agent_id=agent_id,
            agent_leg=AGENT_LEG_REPORT,
        )
        logger.log_entry(entry, tool_name="SubagentStop", tool_category="message_agent",
                         event_time=event_time, raw_json=json_input)
        emitted += 1
    if emitted:
        debug_log(
            f"Captured {emitted} AGENT entr{'y' if emitted == 1 else 'ies'} for "
            f"{agent_ctx}/{agent_id} (SubagentStop; {len(internal)} internal, "
            f"{'report' if report is not None else 'no report'})"
        )
