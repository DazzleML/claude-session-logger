"""One-off: run the v0.3.16 untyped-agent migration against ONE real session
directory, out of band (the hook runs it only on the first event of a run).

Dry-run by default: lists the legacy `.agents-a<16hex>_*` files that would be
merged and where the feed would go. `--apply` performs the migration through
the production function (`cclogger.file_io.migrate_untyped_agent_files`):
entries merged in timestamp order into the `.agents-untyped_*` feed, originals
MOVED (never deleted) to `baks/untyped-<date>/` with a MANIFEST.txt, sentinel
dropped. Recovery: move the files back out of baks/ and delete the sentinel.

Usage:
  python migrate_untyped_dir.py <session_dir>            # dry run
  python migrate_untyped_dir.py <session_dir> --apply
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hooks" / "scripts"))

ID_FILE = re.compile(r"^\.agents-a[0-9a-f]{16}_(?P<shell>.+?)(?:__(?P<name>.+?))?__?(?P<guid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_(?P<user>\w+)(?:\.log)?$")
DIR_RE = re.compile(r"^(?:(?P<name>.+?)__)?(?P<guid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_(?P<user>\w+)$")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    d = Path(argv[0])
    apply = "--apply" in argv
    m = DIR_RE.match(d.name)
    if not d.is_dir() or not m:
        print(f"not a session directory: {d}")
        return 2
    name, guid, user = m.group("name"), m.group("guid"), m.group("user")
    legacy = sorted(p for p in d.iterdir() if p.is_file() and p.name.startswith(".agents-a") and guid in p.name
                    and re.match(r"^\.agents-a[0-9a-f]{16}_", p.name))
    # shell token comes from any existing log file: `.<base>_<shell>__...` or `.<base>_<shell>_<guid>`
    shell = None
    for p in d.iterdir():
        if p.is_file() and p.name.startswith(".") and guid in p.name and "_" in p.name:
            rest = p.name.split("_", 1)[1]
            shell = rest.split("__", 1)[0] if "__" in rest else rest.split(f"_{guid}", 1)[0]
            break
    from cclogger.reconciliation import build_filename
    feed = d / build_filename("", "agents-untyped", shell or "bash.exe", name, guid, user, seq=None)
    print(f"session dir : {d.name}\n  name={name!r} guid={guid} user={user} shell={shell!r}")
    print(f"legacy files: {len(legacy)}")
    for p in legacy:
        print(f"  {p.name[:60]}  ({p.stat().st_size} bytes)")
    print(f"feed target : {feed.name}  ({'exists' if feed.exists() else 'will be created'})")
    sentinel = d / ".session-logger-untyped-migrated"
    print(f"sentinel    : {'present (migration would be a no-op)' if sentinel.exists() else 'absent'}")
    if not apply:
        print("dry run only -- pass --apply to migrate")
        return 0
    from cclogger.file_io import migrate_untyped_agent_files
    moved = migrate_untyped_agent_files(d, guid, name, shell or "bash.exe", user)
    print(f"migrated    : {moved} file(s) moved")
    baks = sorted((d / "baks").glob("untyped-*"))
    print(f"baks        : {[b.name for b in baks]}")
    if feed.exists():
        text = feed.read_text(encoding="utf-8", errors="replace")
        print(f"feed lines  : {text.count(chr(10))}; head:")
        for line in text.splitlines()[:3]:
            # Windows consoles default to cp1252; the feed banner is Unicode.
            print("   ", line[:120].encode("ascii", "replace").decode("ascii"))
    print(f"root id-files remaining: {sum(1 for p in d.iterdir() if p.is_file() and re.match(r'^\\.agents-a[0-9a-f]{16}_', p.name))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
