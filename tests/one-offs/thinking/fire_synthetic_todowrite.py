"""Fire a synthetic TodoWrite event through the live installed hook.

Uses an isolated test session_id so it doesn't pollute the user's real
sesslog dirs. After running, the synthetic dir under sesslogs/ should
contain a `.tasks_*.log` with a `TODOS: ...` entry, proving the new
#87 routing works end-to-end (not just in mocked unit tests).
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

# Use a stable synthetic session ID so reruns land in one place
SESSION_ID = "ffffffff-test-todowrite-87-ffffffffffff"
SESSION_NAME = "TASK87-LIVE-TODOWRITE-SMOKE"
USERNAME = os.environ.get("USERNAME", "Extreme")

HOOK_PATH = Path(
    r"C:\code\claude-projects\claude-session-logger\github\hooks\scripts\log-command.py"
)
SESSLOGS_ROOT = Path.home() / ".claude" / "sesslogs"
SESSION_DIR = SESSLOGS_ROOT / f"{SESSION_NAME}__{SESSION_ID}_{USERNAME}"


def fire_event(event_payload: dict) -> tuple[int, str, str]:
    """Pipe JSON to the hook and return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(event_payload),
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    # 1. SessionStart so directory + run marker get created
    session_start = {
        "hook_event_name": "SessionStart",
        "session_id": SESSION_ID,
        "session_name": SESSION_NAME,
    }
    rc, _, err = fire_event(session_start)
    print(f"[1] SessionStart -> rc={rc}{' ' + err if err else ''}")

    # 2. TodoWrite event (todo category; should now also route to tasks via #87)
    todowrite = {
        "hook_event_name": "PostToolUse",
        "tool_name": "TodoWrite",
        "tool_input": {
            "todos": [
                {"content": "Verify TodoWrite routes to tasks channel",
                 "status": "in_progress",
                 "activeForm": "Verifying TodoWrite routing"},
                {"content": "Verify mcp_server_routes default for todoai",
                 "status": "pending",
                 "activeForm": "Verifying mcp_server_routes"},
                {"content": "Check formatter produces TODOS: ... output",
                 "status": "completed",
                 "activeForm": "Checking formatter"},
            ]
        },
        "tool_response": {"success": True},
        "session_id": SESSION_ID,
        "session_name": SESSION_NAME,
    }
    rc, _, err = fire_event(todowrite)
    print(f"[2] TodoWrite -> rc={rc}{' ' + err if err else ''}")

    # 3. Synthetic Todoist MCP event (server=todoai; should route to tasks via mcp_server_routes default)
    todoist = {
        "hook_event_name": "PostToolUse",
        "tool_name": "mcp__todoai__todoist_create_task",
        "tool_input": {"content": "Synthetic Todoist task from #87 smoke test"},
        "tool_response": {"success": True, "task_id": 9999},
        "session_id": SESSION_ID,
        "session_name": SESSION_NAME,
    }
    rc, _, err = fire_event(todoist)
    print(f"[3] mcp__todoai__todoist_create_task -> rc={rc}{' ' + err if err else ''}")

    # 4. Synthetic NON-Todoist MCP event (server=github; should NOT route to tasks)
    github = {
        "hook_event_name": "PostToolUse",
        "tool_name": "mcp__github__create_issue",
        "tool_input": {"title": "smoke test", "body": "should not land in tasks"},
        "tool_response": {"success": True},
        "session_id": SESSION_ID,
        "session_name": SESSION_NAME,
    }
    rc, _, err = fire_event(github)
    print(f"[4] mcp__github__create_issue -> rc={rc}{' ' + err if err else ''}")

    # 5. Report what landed
    print("\n=== Session dir contents ===")
    if SESSION_DIR.exists():
        for f in sorted(SESSION_DIR.iterdir()):
            if f.is_file() and not f.name.startswith(".session-logger") and f.name != "README.session-logger.md":
                size = f.stat().st_size
                print(f"  {f.name}  ({size} bytes)")
    else:
        print(f"  (session dir not created at {SESSION_DIR})")
        return 1

    # 6. Show the tasks log content
    tasks_glob = list(SESSION_DIR.glob(".tasks_*.log"))
    if tasks_glob:
        print(f"\n=== {tasks_glob[0].name} ===")
        print(tasks_glob[0].read_text(encoding="utf-8"))
    else:
        print("\n(NO .tasks_*.log was created -- routing failed)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
