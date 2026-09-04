# Mutation survivors triaged as equivalent / don't-care

Guarded authority, not an allowlist: entries are grouped under the target file with its content hash (`git hash-object`, first 12). When the file's hash no longer matches, every entry under it is STALE -- re-triage before reuse. Only separated-generation runs (mode 1/2) may write here.

## hooks/scripts/cclogger/file_io.py @ 25fa7e24225b

- `_ENTRY_STAMP = re.compile(r"^\[\[(...)\]\]")` -> same without the `^` anchor — **equivalent**. The pattern is only ever used through `.match()`, which anchors at position 0 regardless of `^`. 2026-09-03, mode 1 (U4 round 2).

## hooks/scripts/cclogger/debug.py @ 15b37413a10e

- `PerfTimer.report`: `if elapsed <= threshold: return False` -> `if elapsed < threshold` — **equivalent in practice**. `elapsed` is a `perf_counter` difference; equality with a configured float threshold is not reproducibly observable, and the contract ("exceeds") holds either way for every real value. 2026-09-03, mode 1 (U5 round 1).
- `report_stale_inflight`: `if age <= threshold: continue` -> `if age < threshold` — **equivalent in practice**, same reasoning (a marker exactly `threshold` seconds old to the microsecond). 2026-09-03, mode 1 (U5 round 1).

## hooks/scripts/cclogger/conversation.py @ fc304f405c57

(Re-hashed 2026-09-03 after unit 5 edited the file; the two U3 entries were re-triaged and still hold -- unit 5 touched neither function.)

- `_read_recent_assistant_blocks`: `if cursor >= size: return []` -> `if cursor > size` — **equivalent**. With the cursor exactly at EOF the mutant opens the file, reads nothing, and rewrites the cursor with the same value; no output, no state, no side effect differs. The early return is an optimisation. 2026-09-03, mode 1 (U3 round 1).
- Stop branch: `n_think = sum(... if k == "thinking")` -> `k == "text"` — **don't-care**: the tally feeds only the debug-log summary line (observability), never an entry or a channel. 2026-09-03, mode 1 (U3 round 1).
- `_handle_subagent_stop` closing bracket: `'report' if report is not None else 'no report'` -> `'report' if report else ...` — **equivalent**. `report` is either `None` or a two-element tuple `(text, when)`, and a non-empty tuple is always truthy, so the two tests agree for every value the code can produce. 2026-09-03, mode 1 (U5 round 2).

## hooks/scripts/log-command.py (no hash: don't-care entries only)

- `print('{"continue": true}')` -> `false` in the FATAL wrapper — **don't-care for the automated suite**: the wrapper predates this unit and is exercised only when `main()` raises; covered by a human checklist line ("break an import, confirm the hook still prints continue: true"). 2026-09-03, mode 1 (U5 round 1).
- `begin_inflight(...)` positional argument swap — **removed as a mutant class**: the call site now uses keyword arguments. 2026-09-03.
