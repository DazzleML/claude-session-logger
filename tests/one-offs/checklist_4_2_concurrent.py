#!/usr/bin/env python3
"""Section 4.2 checklist test: concurrent hook invocations don't race-condition.

Simulates multiple processes writing the same sentinel file simultaneously.
Uses threading to approximate concurrent access within a single process.
"""
import sys, importlib, pathlib, threading, tempfile, shutil

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "hooks" / "scripts"))
mod = importlib.import_module("log-command")

tmpdir = pathlib.Path(tempfile.mkdtemp())
original = mod.UNKNOWN_TOOL_WARN_DIR
mod.UNKNOWN_TOOL_WARN_DIR = tmpdir / "sentinels"

errors = []
results = []

def call_warn():
    try:
        mod._warn_unknown_tool_once("ConcurrentTool", ["foo"])
        results.append("ok")
    except Exception as e:
        errors.append(str(e))

threads = [threading.Thread(target=call_warn) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()

sentinel = (tmpdir / "sentinels" / "ConcurrentTool.warned")
sentinel_count = 1 if sentinel.exists() else 0

print(f"{'PASS' if not errors else 'FAIL'}: No exceptions raised ({len(errors)} errors)")
print(f"{'PASS' if sentinel_count == 1 else 'FAIL'}: Exactly 1 sentinel file exists (got: {sentinel_count})")
print(f"  Successful calls: {len(results)}/10")
if errors:
    for e in errors:
        print(f"  ERROR: {e}")

mod.UNKNOWN_TOOL_WARN_DIR = original
shutil.rmtree(tmpdir, ignore_errors=True)
