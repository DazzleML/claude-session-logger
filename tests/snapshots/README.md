# Snapshot tests for `log-command.py` differential verification

Used to gate behavioral equivalence across the v0.3.7 modularization and channel-options refactor. Each phase ends with a green snapshot diff; non-zero diffs flag a regression.

## Files

- **`synthetic_events.py`** — 25-event fixture covering all hook types (SessionStart, PostToolUse for major tool categories, UserPromptSubmit, Stop, SubagentStop, context compaction).
- **`diff_check.py`** — runner. Pipes each synthetic event into the hook subprocess with redirected `HOME`/`USERPROFILE`/`USERNAME`, captures resulting log files, normalizes timestamps, diffs against a locally-captured baseline.
- **`v036_baseline/`** (gitignored) — locally-captured snapshot of the v0.3.6 hook's log output. Created on demand; never committed.

## Workflow

1. **Before starting any v0.3.7 phase** (one-time per checkout):
   ```bash
   python tests/snapshots/diff_check.py --capture-baseline
   ```
   Captures ~8 log files under `tests/snapshots/v036_baseline/`.

2. **After each phase commit**:
   ```bash
   python tests/snapshots/diff_check.py
   ```
   Exit code 0 = byte-identical to baseline. Non-zero prints a unified diff.

3. **When intentional behavior changes land** (Phase 2+3 onward — e.g., convo channel becomes full-text instead of preview):
   - Re-capture the baseline after verifying the new output is correct: `rm -rf tests/snapshots/v036_baseline && python tests/snapshots/diff_check.py --capture-baseline`
   - Or update the diff expectations in `synthetic_events.py` if the change is structural

## Why baselines aren't committed

- **Platform-dependent**: `Path.resolve()` produces OS-specific absolute paths. A baseline captured on Windows shows `C:\tmp\...`; the same hook on Linux produces `/tmp/...`. Cross-platform a committed baseline would always diff falsely.
- **Trivially reproducible**: `--capture-baseline` regenerates them in seconds.
- **Workflow is local-only**: each developer captures their baseline on their machine before starting a refactor phase, runs the diff after each phase. The baseline never needs to cross machines.

## Coverage

The 25-event fixture in `synthetic_events.py` exercises:

| Hook event | Tool/scenario coverage |
|---|---|
| `SessionStart` | First-run + compaction (`source: compact`) |
| `PostToolUse` | Bash, PowerShell, Grep, Glob, LS (bash category); Read (system); Write, Edit, MultiEdit (io); WebSearch, WebFetch (search); TodoWrite (todo); TaskCreate (task); Task (meta); Skill (skill); MCP namespaced tool (mcp); AskUserQuestion (ui); unknown tool (unknowns channel) |
| `UserPromptSubmit` | Single-line + multi-line with embedded quotes/backticks |
| `Stop` | AI text response from synthetic transcript |
| `SubagentStop` | Agent dialogue from synthetic transcript |

Output is captured across the 6 default channels (shell, sesslog, tools, tasks, convo, unknowns) for the main session plus 2 channels (shell, sesslog) for the subagent session.

## Limitations

- Baseline lives on the developer's machine; CI/cross-machine verification not supported by this harness.
- Path strings inside log entries (e.g., `cwd`-resolved paths from Grep) carry OS-specific separators — the baseline captures the local machine's behavior.
- Future enhancement: portable baseline if needed (would require synthesizing path-resolution behavior or normalizing paths in addition to timestamps).
