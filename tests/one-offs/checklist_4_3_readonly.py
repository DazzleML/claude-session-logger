#!/usr/bin/env python3
"""Section 4.3 checklist test: sentinel directory read-only tolerance."""
import sys, importlib, pathlib, os, stat, shutil, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "hooks" / "scripts"))
mod = importlib.import_module("log-command")

tmpdir = pathlib.Path(tempfile.mkdtemp())
readonly_dir = tmpdir / "readonly_sentinels"
readonly_dir.mkdir()
readonly_dir.chmod(stat.S_IREAD | stat.S_IEXEC)

original = mod.UNKNOWN_TOOL_WARN_DIR
mod.UNKNOWN_TOOL_WARN_DIR = readonly_dir

try:
    mod._warn_unknown_tool_once("SomeTool", ["foo", "bar"])
    print("PASS: _warn_unknown_tool_once silently tolerated read-only dir")
except Exception as e:
    print("FAIL: raised exception:", e)
finally:
    mod.UNKNOWN_TOOL_WARN_DIR = original
    try:
        readonly_dir.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        shutil.rmtree(tmpdir)
    except Exception:
        pass
