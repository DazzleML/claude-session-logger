"""Fire a synthetic TaskOutput event with verbose output to see what lands
in each channel under existing per-channel verbosity caps.

Helps decide: do shell+tools max_chars=100 give useful TaskOutput snippets,
or do we still want to drop TaskOutput from shell/tools?
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SESSION_ID = "eeeeeeee-test-taskoutput-87-eeeeeeeeeeee"
SESSION_NAME = "TASK87-LIVE-TASKOUTPUT-SMOKE"
USERNAME = os.environ.get("USERNAME", "Extreme")

HOOK_PATH = Path(
    r"C:\code\claude-projects\claude-session-logger\github\hooks\scripts\log-command.py"
)
SESSLOGS_ROOT = Path.home() / ".claude" / "sesslogs"
# Hook will create dir as `__<id>_<user>/` since session_name isn't picked up
# from PostToolUse payload field (known smoke-harness quirk).
SESSION_DIR_GUESS = SESSLOGS_ROOT / f"__{SESSION_ID}_{USERNAME}"


def fire_event(event_payload: dict) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(event_payload),
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return proc.returncode, proc.stdout, proc.stderr


# Simulated long output from a running dev server (typical npm run dev shape)
SIMULATED_OUTPUT = """\
[next-dev] ready - started server on 0.0.0.0:3000, url: http://localhost:3000
[next-dev] info  - Loaded env from .env.local
[next-dev] info  - Using next.config.js
[next-dev] event - compiled client and server successfully in 2.3s
[next-dev] wait  - compiling /api/health (client and server)...
[next-dev] event - compiled successfully in 142ms
[next-dev] info  - 200 GET /api/health 142ms
[next-dev] wait  - compiling / ...
[next-dev] event - compiled successfully in 1.2s
[next-dev] info  - 200 GET / 1240ms
[next-dev] info  - 200 GET /_next/static/css/app.css 12ms
[next-dev] info  - 200 GET /_next/static/chunks/webpack.js 8ms
[error] Unhandled promise rejection in /pages/api/users.ts:42
[error]   TypeError: Cannot read property 'id' of undefined
[error]     at handler (/app/pages/api/users.ts:42:18)
[error]     at Object.apiResolver (/node_modules/next/dist/server/api-utils.js:101:15)
"""

def main() -> int:
    fire_event({
        "hook_event_name": "SessionStart",
        "session_id": SESSION_ID,
        "session_name": SESSION_NAME,
    })

    fire_event({
        "hook_event_name": "PostToolUse",
        "tool_name": "TaskOutput",
        "tool_input": {"task_id": "42", "block": True, "timeout": 30000},
        "tool_response": {
            "retrieval_status": "success",
            "task": {
                "task_id": "42",
                "task_type": "local_bash",
                "status": "running",
                "description": "npm run dev",
                "output": SIMULATED_OUTPUT,
                "exitCode": None,
            },
        },
        "session_id": SESSION_ID,
        "session_name": SESSION_NAME,
    })

    fire_event({
        "hook_event_name": "PostToolUse",
        "tool_name": "TaskStop",
        "tool_input": {"task_id": "42"},
        "tool_response": {
            "message": "Task 42 stopped successfully",
            "task_id": "42",
            "task_type": "local_bash",
            "command": "npm run dev",
        },
        "session_id": SESSION_ID,
        "session_name": SESSION_NAME,
    })

    if not SESSION_DIR_GUESS.exists():
        # Look for the actual session dir
        for d in SESSLOGS_ROOT.iterdir():
            if SESSION_ID in d.name:
                session_dir = d
                break
        else:
            print(f"ERROR: no session dir for {SESSION_ID}")
            return 1
    else:
        session_dir = SESSION_DIR_GUESS

    print(f"\n=== Session dir: {session_dir.name} ===\n")
    for channel in ("shell", "sesslog", "tools", "tasks"):
        log_files = list(session_dir.glob(f".{channel}_*.log"))
        if not log_files:
            print(f"--- .{channel}_*.log: NOT CREATED ---\n")
            continue
        content = log_files[0].read_text(encoding="utf-8")
        # Skip the SESSION START banner; show only entries
        entries = [ln for ln in content.split("\n") if ln.startswith("[[")]
        print(f"--- .{channel}_*.log ({len(entries)} entries) ---")
        for line in entries:
            print(f"  {line}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
