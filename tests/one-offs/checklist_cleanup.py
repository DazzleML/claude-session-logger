#!/usr/bin/env python3
"""Cleanup script: remove synthetic test session files created by checklist runs."""
import shutil, pathlib

base = pathlib.Path.home() / ".claude" / "sesslogs"
removed = []

patterns = ["test-fake-checklist", "test-fake-checklist-hv", "test-fake-checklist-s4"]

for item in list(base.iterdir()):
    name = item.name
    if any(p in name for p in patterns):
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
        removed.append(name)

# Also clean throttle sentinel dir
warn_dir = pathlib.Path.home() / ".claude" / "logs" / ".unknown_tool_warnings"
if warn_dir.exists():
    shutil.rmtree(warn_dir)
    removed.append(f"(throttle sentinel dir)")

print(f"Removed {len(removed)} items:")
for r in removed:
    print(f"  - {r}")
