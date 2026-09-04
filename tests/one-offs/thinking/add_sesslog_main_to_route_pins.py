"""One-shot (2026-09-03, sidechain-capture unit 6): `sesslog-main` joins every
default route that names `sesslog`, right after it. Eighteen assertions in
seven test files pin those default lists literally; this applies the same
insertion to each so the pins keep guarding the (new) defaults.

Only DEFAULT-list literals are touched (the exact strings below); a test
that asserts a user override such as `["sesslog"]` or `["shell"]` is not
matched and stays as it is. Prints a per-file count; run with --dry-run to
see counts without writing.

Usage: python tests/one-offs/thinking/add_sesslog_main_to_route_pins.py [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FILES = [
    "tests/one-offs/test_agent_context_routing.py",
    "tests/one-offs/test_conversation_channels.py",
    "tests/one-offs/test_config_merge_protocol.py",
    "tests/one-offs/test_subtype_routing.py",
    "tests/one-offs/test_tasks_channel_coverage.py",
    "tests/one-offs/test_tools_channel.py",
    "tests/one-offs/test_unknown_tool_routing.py",
]
REPLACEMENTS = [
    ('["shell", "sesslog", "tools"', '["shell", "sesslog", "sesslog-main", "tools"'),
    ('["sesslog", "convo"]', '["sesslog", "sesslog-main", "convo"]'),
    ('["sesslog", "unknowns"]', '["sesslog", "sesslog-main", "unknowns"]'),
    ('["sesslog", "agents"]', '["sesslog", "sesslog-main", "agents"]'),
    ('["sesslog", "tools", "tools-output"]', '["sesslog", "sesslog-main", "tools", "tools-output"]'),
]


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    total = 0
    for rel in FILES:
        path = REPO / rel
        with path.open(encoding="utf-8", newline="") as fh:
            text = fh.read()
        new = text
        n = 0
        for old, rep in REPLACEMENTS:
            n += new.count(old)
            new = new.replace(old, rep)
        if n and not dry:
            with path.open("w", encoding="utf-8", newline="") as fh:
                fh.write(new)
        print(f"{'would change' if dry else 'changed'} {n:2d}  {rel}")
        total += n
    print(f"total replacements: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
