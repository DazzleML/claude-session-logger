"""Red-green audit helper for unit 6 (sesslog-main) of the sidechain-capture
design (2026-09-03): strip the unit's production change from an ISOLATED
COPY of models.py so tests/one-offs/test_sesslog_main.py can be shown red
without touching the live working tree (hooks run live from it).

What it removes: the `"sesslog-main": ChannelConfig(...)` block in
_default_channels() and every `"sesslog-main", ` element in the route and
override lists. Nothing else changes.

Usage: python strip_u6_for_audit.py <copy-root>   (root containing hooks/)
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
path = root / "hooks" / "scripts" / "cclogger" / "models.py"
src = path.read_text(encoding="utf-8")

start = src.index('        "sesslog-main": ChannelConfig(')
end = src.index("        ),\n", start) + len("        ),\n")
block = src[start:end]
assert block.count("ChannelConfig(") == 1 and 'file_prefix=".sesslog-main_"' in block, block
stripped = src[:start] + src[end:]

n_routes = stripped.count('"sesslog-main", ')
assert n_routes == 11, n_routes
stripped = stripped.replace('"sesslog-main", ', "")
assert '"sesslog-main"' not in stripped.replace('"sesslog-main": {"enabled": false}', "")

path.write_text(stripped, encoding="utf-8")
print(f"stripped channel block ({block.count(chr(10))} lines) + {n_routes} route mentions from {path}")
