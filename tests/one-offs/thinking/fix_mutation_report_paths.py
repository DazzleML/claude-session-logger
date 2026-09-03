"""One-shot: repair the mutation reports' redacted scratchpad path.

Every ``tests/mutation/*.report.json`` written during the v0.3.16 sweeps
carries ``"root": "<session-scratchpad>\\mut-root..."`` with a SINGLE
backslash after the redaction token -- an invalid JSON escape, so none of
the ten reports parses (found by the v0.3.17 last-mile check, 2026-09-03).
The spec ``.json`` files are unaffected.

Fix: inside the ``root`` value only, turn backslashes into forward slashes
(the value is a redacted, non-resolvable label, so the separator carries no
meaning). Verify each file parses afterwards; leave any file that still
fails untouched and report it.

Usage: python tests/one-offs/thinking/fix_mutation_report_paths.py [--dry-run]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REPORTS = sorted((REPO / "tests" / "mutation").glob("*.report.json"))
ROOT_FIELD = re.compile(r'("root":\s*")([^"\n]*)(")')


def repair(text: str) -> str:
    def _sub(m: re.Match) -> str:
        return m.group(1) + m.group(2).replace("\\", "/") + m.group(3)
    return ROOT_FIELD.sub(_sub, text)


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    bad = 0
    for path in REPORTS:
        with path.open(encoding="utf-8", newline="") as fh:  # keep CRLF as-is
            raw = fh.read()
        try:
            json.loads(raw)
            print(f"ok       {path.name}")
            continue
        except json.JSONDecodeError as exc:
            before = f"line {exc.lineno} col {exc.colno}"
        fixed = repair(raw)
        try:
            json.loads(fixed)
        except json.JSONDecodeError as exc:
            print(f"STILL-BAD {path.name}: {exc} (was {before})")
            bad += 1
            continue
        if dry:
            print(f"would fix {path.name} (was {before})")
        else:
            with path.open("w", encoding="utf-8", newline="") as fh:  # no translation
                fh.write(fixed)
            print(f"fixed    {path.name} (was {before})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
