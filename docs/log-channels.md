# Log Channels

claude-session-logger creates separate log files for different types of activity, allowing you to monitor specific aspects of your Claude Code sessions.

## Log File Types

### Session Log (`.sesslog_*.log`)

**Purpose**: High-level tool usage tracking

**Contains**:
- Timestamps for each tool call
- Tool names (Read, Write, Edit, Bash, Glob, Grep, etc.)
- Session start/resume markers
- Run number tracking

**Example output**:
```
=== Run #1 started at 2026-01-29 10:30:15 ===
[[2026-01-29 10:30:16]] {Read: /path/to/file.py}
[[2026-01-29 10:30:18]] {Edit: /path/to/file.py}
[[2026-01-29 10:30:25]] {Bash: pytest tests/}
[[2026-01-29 10:31:02]] {Write: /path/to/new_file.py}
```

**Use cases**:
- Quick scan of what Claude did in a session
- Identify which files were touched
- Track session timing and duration

### Shell Log (`.shell_*.log`)

**Purpose**: Detailed bash command output

**Contains**:
- Full command strings executed
- Command output (stdout/stderr)
- Exit codes
- Working directory context

**Example output**:
```
[[2026-01-29 10:30:25]] $ pytest tests/ -v
============================= test session starts =============================
collected 15 items
tests/test_paths.py::test_normalize PASSED
tests/test_paths.py::test_cross_platform PASSED
...
============================= 15 passed in 2.34s ==============================
[[EXIT: 0]]
```

**Use cases**:
- Debug failed commands
- Copy-paste command output
- Review build/test results
- Audit what was executed on your system

### Task Log (`.tasks_*.log`)

**Purpose**: Claude Code task operations tracking

**Contains**:
- TaskCreate: New tasks with subjects and descriptions
- TaskUpdate: Status changes (pending → in_progress → completed)
- TaskList: Task queries
- TaskGet: Task detail retrievals

**Example output**:
```
[[2026-01-29 10:32:00]] {CREATE #1: Implement user authentication | Add login/logout...}
[[2026-01-29 10:35:00]] {UPDATE: #1 -> in_progress}
[[2026-01-29 10:45:00]] {UPDATE: #1 -> completed}
[[2026-01-29 10:45:05]] {CREATE #2: Add unit tests | Cover auth module...}
```

**Use cases**:
- Track task progress over time
- Review what Claude planned to do
- Correlate tasks with actual work done
- Audit task lifecycle

## Sesslog vs Shell: Key Differences

| Aspect | Sesslog | Shell |
|--------|---------|-------|
| Scope | All tool calls | Bash commands only |
| Detail | Tool name + target | Full command + output |
| Size | Compact | Can grow large |
| Purpose | Overview/audit | Debugging/review |
| Real-time use | "What is Claude doing now?" | "What did that command output?" |

## Real-Time Monitoring

You can `tail -f` any of these logs to watch Claude Code work in real-time:

```bash
# Watch all tool calls
tail -f ~/.claude/sesslogs/my-project__abc123_User/.sesslog_*.log

# Watch bash commands and output
tail -f ~/.claude/sesslogs/my-project__abc123_User/.shell_*.log

# Watch task operations
tail -f ~/.claude/sesslogs/my-project__abc123_User/.tasks_*.log
```

This is particularly useful for:
- **Spot-checking**: Verify Claude is doing what you expect
- **Copy-pasting**: Grab command output without scrolling through Claude's UI
- **Learning**: See the exact commands Claude uses to accomplish tasks
- **Debugging**: Catch errors as they happen

## Overflow Handling

When log files exceed a size threshold, they're rotated:
- `file.log` → `file.log.overflow.1`
- New content continues in `file.log`

This prevents individual log files from growing unboundedly while preserving history.

## Transcript Symlink

Each sesslog directory also contains a `transcript.jsonl` symlink pointing to Claude Code's full conversation transcript:

```
~/.claude/sesslogs/my-project__abc123_User/
├── .sesslog_*.log
├── .shell_*.log
├── .tasks_*.log
└── transcript.jsonl → ~/.claude/projects/.../abc123.jsonl
```

This provides easy access to the complete conversation without navigating Claude's internal directory structure.
