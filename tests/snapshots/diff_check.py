#!/usr/bin/env python3
"""Snapshot baseline + differential test for log-command.py output.

Pipes the synthetic event sequence (synthetic_events.EVENTS) into the hook
subprocess with HOME/USERPROFILE/USERNAME redirected to a temp dir, captures
the resulting `.log` files under <tmp>/.claude/sesslogs/, normalizes timestamps,
and compares byte-for-byte against tests/snapshots/v036_baseline/.

The baseline directory is GITIGNORED and locally captured by each developer
before starting the v0.3.7 modularization. Baselines are platform-dependent
(Path.resolve() produces OS-specific paths) so a single committed baseline
would diff falsely across machines. Workflow:

  1. python tests/snapshots/diff_check.py --capture-baseline   # one-time setup
  2. (do refactor phase work)
  3. python tests/snapshots/diff_check.py                       # verify

After each v0.3.7 phase, this script must report byte-identical output
(modulo intentional deltas documented in the plan file). See README.md
in this directory for the full workflow.

Exit codes:
  0 = byte-identical to baseline
  1 = diff detected (prints unified diff)
  2 = error (subprocess failure, missing baseline, etc.)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from difflib import unified_diff
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_SCRIPT = REPO_ROOT / "hooks" / "scripts" / "log-command.py"
SNAPSHOT_DIR = Path(__file__).resolve().parent
BASELINE_DIR = SNAPSHOT_DIR / "v036_baseline"

# Fixed username for deterministic file naming across machines
SNAPSHOT_USERNAME = "snapuser"

# Patterns to normalize before diff (timestamps vary every run)
TIMESTAMP_RE = re.compile(r'\[\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\]')
SESSION_MARKER_TS_RE = re.compile(
    r'(═══ (?:SESSION START|CONTEXT COMPACTED)  •  )\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
)


def run_synthetic_session(home_dir: Path) -> None:
    """Pipe each synthetic event into the hook subprocess.

    HOME/USERPROFILE/USERNAME are set so the hook writes into home_dir
    instead of the real ~/.claude/. The synthetic transcript is written
    into home_dir as well, and each event's transcript_path is rewritten
    to point at it (so Stop/SubagentStop handlers can read it).
    """
    sys.path.insert(0, str(SNAPSHOT_DIR))
    try:
        from synthetic_events import EVENTS, SYNTHETIC_TRANSCRIPT_LINES
    finally:
        sys.path.pop(0)

    transcript_path = home_dir / "synthetic_transcript.jsonl"
    transcript_path.write_text("\n".join(SYNTHETIC_TRANSCRIPT_LINES) + "\n", encoding="utf-8")

    cwd_override = home_dir / "synthetic-test-project"
    cwd_override.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["USERPROFILE"] = str(home_dir)
    env["HOME"] = str(home_dir)
    env["USERNAME"] = SNAPSHOT_USERNAME
    # Drop any existing dazzle-filekit cache that might point at the real home
    env.pop("DAZZLE_FILEKIT_CACHE", None)

    failures = 0
    for i, event in enumerate(EVENTS):
        e = dict(event)
        e["transcript_path"] = str(transcript_path)
        # Don't override cwd if the event explicitly set one (some categorize differently)
        # but for snapshot determinism, force a fixed cwd
        e["cwd"] = str(cwd_override)

        proc = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT)],
            input=json.dumps(e),
            text=True,
            env=env,
            capture_output=True,
            timeout=15,
        )
        if proc.returncode != 0:
            failures += 1
            event_label = f"{e.get('hook_event_name')} {e.get('tool_name', '')}".strip()
            print(f"WARNING: event {i} ({event_label}) exited {proc.returncode}",
                  file=sys.stderr)
            if proc.stderr:
                print(f"  stderr: {proc.stderr[:300]}", file=sys.stderr)

    if failures:
        print(f"NOTE: {failures}/{len(EVENTS)} events exited non-zero "
              "(may be expected for some hook contracts)", file=sys.stderr)


def normalize(content: str) -> str:
    """Strip variable bits (timestamps) from log content for byte comparison."""
    content = TIMESTAMP_RE.sub('[[TIMESTAMP]]', content)
    content = SESSION_MARKER_TS_RE.sub(r'\1TIMESTAMP', content)
    return content


def collect_log_files(sesslogs_root: Path) -> dict[str, str]:
    """Walk sesslogs/ and return {relative-posix-path: normalized content}.

    Only `.log` files are collected; transcript symlinks and state files
    are excluded. Filename includes session subdirectory.
    """
    files: dict[str, str] = {}
    if not sesslogs_root.exists():
        return files
    for path in sorted(sesslogs_root.rglob("*.log")):
        if not path.is_file():
            continue
        rel = path.relative_to(sesslogs_root).as_posix()
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            content = f"<read error: {e}>"
        files[rel] = normalize(content)
    return files


def capture_baseline() -> int:
    if BASELINE_DIR.exists():
        print(f"ERROR: baseline already exists at {BASELINE_DIR}", file=sys.stderr)
        print("Delete the directory first if you intend to recapture.", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="cclogger-snap-baseline-") as tmp:
        home = Path(tmp)
        run_synthetic_session(home)
        sesslogs = home / ".claude" / "sesslogs"
        files = collect_log_files(sesslogs)
        if not files:
            print("ERROR: no log files produced — hook likely failed for every event",
                  file=sys.stderr)
            return 2
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        for rel, content in files.items():
            out = BASELINE_DIR / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding="utf-8")
        print(f"Captured {len(files)} log file(s) to {BASELINE_DIR.relative_to(REPO_ROOT)}")
    return 0


def diff_against_baseline() -> int:
    if not BASELINE_DIR.exists():
        print(f"ERROR: baseline not found at {BASELINE_DIR}", file=sys.stderr)
        print("Run: python tests/snapshots/diff_check.py --capture-baseline", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="cclogger-snap-actual-") as tmp:
        home = Path(tmp)
        run_synthetic_session(home)
        actual = collect_log_files(home / ".claude" / "sesslogs")

    baseline = collect_log_files(BASELINE_DIR)

    diffs = []
    all_keys = sorted(set(baseline.keys()) | set(actual.keys()))
    for k in all_keys:
        if k not in baseline:
            diffs.append(f"NEW FILE (not in baseline): {k}\n")
        elif k not in actual:
            diffs.append(f"MISSING FILE (in baseline but not in actual): {k}\n")
        elif baseline[k] != actual[k]:
            diff = list(unified_diff(
                baseline[k].splitlines(keepends=True),
                actual[k].splitlines(keepends=True),
                fromfile=f"baseline/{k}",
                tofile=f"actual/{k}",
                n=3,
            ))
            diffs.append("".join(diff))

    if diffs:
        print("DIFF DETECTED:")
        for d in diffs:
            print(d)
        return 1

    print(f"Byte-identical to baseline ({len(actual)} log file(s))")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--capture-baseline", action="store_true",
        help="Write current synthetic session output as the baseline (refuses if exists)",
    )
    args = parser.parse_args()

    if args.capture_baseline:
        sys.exit(capture_baseline())
    else:
        sys.exit(diff_against_baseline())


if __name__ == "__main__":
    main()
