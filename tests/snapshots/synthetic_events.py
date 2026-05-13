"""Synthetic hook events for byte-identical snapshot testing.

Each event mirrors the JSON shape Claude Code sends to log-command.py via stdin.
Designed to exercise:
- Every hook event type (SessionStart, PostToolUse, UserPromptSubmit, Stop, SubagentStop)
- All major tool categories (bash, system, io, task, todo, meta, search, ui, skill, mcp, unknown)
- Both shell and powershell subtypes
- Compaction (SessionStart with source=compact)
- Multi-line content (Edit with newlines, user prompt with newlines)

Used by diff_check.py to verify byte-identical log output across the v0.3.7
modularization refactor. Baseline captured under v0.3.6 commit 35c1535.
"""

# Fixed identifiers — the snapshot test redirects HOME/USERPROFILE to a tmp dir
# but the hook reads session_id from the event. Using fixed values keeps file
# names deterministic for diff comparison.
SESSION_ID = "00000000-0000-0000-0000-000000000001"
SUBAGENT_SESSION_ID = "00000000-0000-0000-0000-000000000002"
CWD = "/tmp/synthetic-test-project"  # cross-platform-friendly fixed path


def _common(extra: dict | None = None, hook_event: str = "PostToolUse",
            session_id: str = SESSION_ID) -> dict:
    """Shared fields for every event."""
    base = {
        "session_id": session_id,
        "transcript_path": "/tmp/synthetic-test-project/.transcript.jsonl",
        "cwd": CWD,
        "hook_event_name": hook_event,
    }
    if extra:
        base.update(extra)
    return base


def _tool(tool_name: str, tool_input: dict, tool_response: dict | None = None) -> dict:
    """A PostToolUse event for a specific tool."""
    return _common({
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": tool_response or {"success": True},
    })


# Order matters: SessionStart first so the rest of the events have a
# session directory to write into.
EVENTS = [
    # Hook event coverage
    _common(hook_event="SessionStart", extra={"source": "startup", "model": "claude-opus-4-7"}),

    # User prompt (UserPromptSubmit)
    _common(hook_event="UserPromptSubmit",
            extra={"user_prompt": "Synthetic prompt one — please show me the file structure."}),

    # Bash (bash category)
    _tool("Bash", {"command": "ls -la /tmp"}),

    # PowerShell (bash category, powershell subtype)
    _tool("PowerShell", {"command": "Get-ChildItem -Path C:\\tmp"}),

    # Grep (bash category as of v0.3.6 — moved from system)
    _tool("Grep", {"pattern": "TODO", "path": "/tmp/synthetic-test-project", "glob": "*.py"}),

    # Glob (bash category as of v0.3.6)
    _tool("Glob", {"pattern": "**/*.py", "path": "/tmp/synthetic-test-project"}),

    # LS (bash category as of v0.3.6)
    _tool("LS", {"path": "/tmp/synthetic-test-project/src"}),

    # Read (system category — stays as structured file read)
    _tool("Read", {"file_path": "/tmp/synthetic-test-project/src/main.py", "offset": 1, "limit": 50}),

    # Write (io category)
    _tool("Write", {"file_path": "/tmp/synthetic-test-project/notes.txt",
                    "content": "Line 1\nLine 2\nLine 3 with embedded \\n escape"}),

    # Edit (io category) — multi-line content + line delta
    _tool("Edit", {"file_path": "/tmp/synthetic-test-project/src/main.py",
                   "old_string": "def main():\n    pass\n",
                   "new_string": "def main():\n    print('hello')\n    return 0\n"}),

    # MultiEdit (io category)
    _tool("MultiEdit", {"file_path": "/tmp/synthetic-test-project/src/main.py",
                        "edits": [
                            {"old_string": "import os", "new_string": "import os\nimport sys"},
                            {"old_string": "FOO = 1", "new_string": "FOO = 2"},
                        ]}),

    # WebSearch (search category)
    _tool("WebSearch", {"query": "claude code hook events documentation"}),

    # WebFetch (search category)
    _tool("WebFetch", {"url": "https://docs.claude.com/en/docs/claude-code/hooks"}),

    # TodoWrite (todo category)
    _tool("TodoWrite", {"todos": [
        {"content": "Build snapshot infrastructure", "status": "in_progress", "activeForm": "Building"},
        {"content": "Capture baseline", "status": "pending", "activeForm": "Capturing"},
    ]}),

    # TaskCreate (task category)
    _tool("TaskCreate", {"subject": "Verify snapshot diff",
                         "description": "Run diff_check.py and confirm byte-identical."}),

    # Agent (meta category — sub-agent invocation; live tool name in Claude
    # Code per source canvass 2026-05-12, was misnamed "Task" before #45 fix)
    _tool("Agent", {"description": "Spawn explore agent",
                    "subagent_type": "Explore",
                    "prompt": "Find all uses of foo()"}),

    # Skill (skill category)
    _tool("Skill", {"skill": "obsidian", "args": "Capture this note about the snapshot test design."}),

    # MCP tool (mcp category — namespaced)
    _tool("mcp__github__create_issue", {"title": "test", "body": "synthetic"}),

    # AskUserQuestion (ui category)
    _tool("AskUserQuestion", {"questions": [{"question": "Do you want X?", "options": ["yes", "no"]}]}),

    # Unknown tool (unknown category — should hit the v0.2.1 unknowns channel)
    _tool("SomeNewToolClaudeJustAdded", {"input_field": "value"}),

    # User prompt with embedded newlines + special chars
    _common(hook_event="UserPromptSubmit",
            extra={"user_prompt": "Multi-line prompt:\nLine 2 with \"quotes\"\nLine 3 with `backticks`"}),

    # Compaction event (SessionStart with source=compact)
    _common(hook_event="SessionStart", extra={"source": "compact", "model": "claude-opus-4-7"}),

    # Post-compaction tool call (run number should be preserved across compaction)
    _tool("Bash", {"command": "echo 'after compaction'"}),

    # Stop event (AI response captured from transcript) — handler reads transcript
    _common(hook_event="Stop"),

    # SubagentStop event (agent dialogue captured from subagent transcript)
    _common(hook_event="SubagentStop", session_id=SUBAGENT_SESSION_ID,
            extra={"subagent_type": "Explore"}),
]


# Synthetic transcript JSONL — used by Stop/SubagentStop handlers.
# The handler reads recent assistant messages since the last cursor; we provide
# enough content for first-call extraction. Subsequent runs of the snapshot
# test will skip already-extracted messages thanks to the cursor.
SYNTHETIC_TRANSCRIPT_LINES = [
    # Assistant message with simple text content (role/content shape)
    '{"role": "assistant", "content": "First synthetic AI response. Acknowledging the prompt."}',
    # Assistant message with structured content blocks (message.content shape)
    '{"message": {"role": "assistant", "content": [{"type": "text", "text": "Second AI response with a code block:\\n\\n```python\\nprint(\\"hello\\")\\n```"}]}}',
    # Tool-use block (should be ignored by text extractor)
    '{"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}',
    # Subagent-style message
    '{"role": "assistant", "content": "Subagent reply: investigation complete."}',
]


def write_synthetic_transcript(path):
    """Write the synthetic transcript JSONL to the given path."""
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(SYNTHETIC_TRANSCRIPT_LINES) + "\n", encoding="utf-8")
