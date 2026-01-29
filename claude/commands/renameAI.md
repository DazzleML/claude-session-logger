---
description: AI-assisted session rename - generates a concise, descriptive name from conversation context.
allowed-tools: Bash, Read, Write, Edit
---

# AI-Assisted Session Rename

Generate a meaningful, concise session name based on conversation content.

**User hints (optional):** "$ARGUMENTS"

**Current Session ID:** ${CLAUDE_SESSION_ID}

## Instructions

### Step 1: Read Session State

First, read the session state file to get context:

```bash
cat ~/.claude/session-states/${CLAUDE_SESSION_ID}.json
```

This provides:
- `transcript_path` - Path to conversation .jsonl
- `sessions_index_path` - Path to sessions-index.json (for backup/update)
- `sesslog_dir` - Current session log directory
- `cwd` - Working directory (project folder)
- `current_name` - Existing session name (if any)

### Step 2: Analyze Context for Name Generation

Consider these sources for the session name:
1. **User hints** (if provided in $ARGUMENTS) - weight these heavily
2. **Working directory name** - often indicates the project
3. **Files discussed** - what was being worked on
4. **Main topics** - bugs fixed, features added, tasks performed

### Step 3: Generate Name Candidates

Create 2-3 candidate names following these rules:

**Format**: `WORD1-WORD2_WORD3_WORD4`
- Dash (`-`) = same concept / compound word (e.g., `session-rename`)
- Underscore (`_`) = word separator (e.g., `fix_auth_bug`)

**Constraints**:
- Lowercase only
- Target: 3-4 words
- Maximum: 10 words
- Characters: alphanumeric, dashes, underscores only
- No spaces, no special characters

**Good examples**:
- `dazzle-filekit_v020_release`
- `fix_session-rename_bug`
- `claude-hooks_stop-event`
- `api_timeout_debug`

**Bad examples**:
- `working-on-stuff` (too vague)
- `comprehensive-refactoring-of-authentication-system` (too long)
- `Fix Auth Bug` (has spaces, uppercase)

### Step 4: Present to User

Show the user your recommendations:

```
Suggested name: [BEST_CANDIDATE]

Based on:
- [rationale - what drove this name choice]

Other options:
- [candidate 2]
- [candidate 3]

Current name: [current_name from state file]
Project folder: [cwd from state file]

Accept this name? (y/n/provide alternative)
```

### Step 5: Apply the Rename (After User Approval)

Once user approves a name, run the rename script:

```bash
python ~/.claude/hooks/rename_session.py ${CLAUDE_SESSION_ID} "APPROVED_NAME"
```

The script will:
1. Create timestamped backup of sessions-index.json
2. Update sessions-index.json with new customTitle
3. Append custom-title entry to transcript .jsonl
4. Report success (folder rename happens on next hook trigger)

## Important Notes

- Always show current name before proposing new one
- Never apply rename without user approval
- If conversation is too short/vague, ask user for hints
- The folder rename happens automatically via the hook system
