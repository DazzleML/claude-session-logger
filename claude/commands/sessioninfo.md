# Session Info

Show information about the current Claude Code session.

## Instructions

Read the session state file at `~/.claude/session-states/${CLAUDE_SESSION_ID}.json` and display the session information in a clear format.

**Session ID**: `${CLAUDE_SESSION_ID}`

Use the Read tool to get the contents of the state file, then present the information like this:

```
Session Information
-------------------
Session ID:    {session_id}
Session Name:  {current_name or "(unnamed)"}
Original Dir:  {original_cwd}
Current Dir:   {cwd}
Sesslog Dir:   {sesslog_dir}
Transcript:    {transcript_path}
Last Updated:  {updated_at}
```

Note: `original_cwd` is the working directory when the session started. `cwd` is the current working directory (may change if user runs `cd` commands).

If the state file doesn't exist, inform the user that the session state hasn't been initialized yet (may happen on very first tool call of a new session).
