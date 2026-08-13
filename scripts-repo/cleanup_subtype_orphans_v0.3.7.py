"""One-shot bulk cleanup: move stale subtype-derived log files to a bak/ folder.

Used after the v0.3.7-pre #49 fix flipped subtype splitting from
category-wide opt-out (`routing.subtype_routing.bash: true` fanned out
`.shell-bash_*`, `.sesslog-bash_*`, `.tools-bash_*`) to per-channel
opt-in (only `agents` defaults true; other channels need explicit
`subtype_split: true`).

After the upgrade, hooks no longer regenerate the unwanted derivatives,
but pre-existing files remain. This script walks every session
directory under ~/.claude/sesslogs/, finds any `.<channel>-<subtype>_*.log`
file where the channel is NOT `agents`, and moves it under
~/.claude/sesslogs/bak/<session-dir-name>/<filename> for recoverable cleanup.

Files preserved (not touched):
- `.agents-*` — intentional split (agents channel defaults subtype_split=True)
- `.<channel>_*` (no `-<subtype>`) — canonical base channel files
- `.session-logger-overflow-migrated`, `.session-logger-orphans-swept`,
  `README.session-logger.md` — state markers + documentation drop
  (and legacy `.overflow_migrated_v0.3.7`, `.orphan_session_name_swept_v0.3.7`)
- `transcript.jsonl` — symlinks
- Anything inside an existing `baks/` or `bak/` subfolder — already cleaned

With --include-legacy-overflows, also targets `.overflow.N` files in
dormant session dirs (pre-#47 cruft whose SessionLogger never reopened
to run the in-process migrate_overflow_files).

Usage:
    # Dry-run subtype-derived files
    python scripts-repo/local/cleanup_subtype_orphans_v0.3.7.py

    # Apply subtype-derived cleanup
    python scripts-repo/local/cleanup_subtype_orphans_v0.3.7.py --apply

    # Include legacy overflows (dry-run)
    python scripts-repo/local/cleanup_subtype_orphans_v0.3.7.py --include-legacy-overflows

    # Apply both
    python scripts-repo/local/cleanup_subtype_orphans_v0.3.7.py --apply --include-legacy-overflows
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


SUBTYPE_PATTERN = re.compile(r"^\.([\w]+)-[\w.-]+_[\w.]+_.*\.log$")
LEGACY_OVERFLOW_PATTERN = re.compile(r"\.overflow\.\d+$")
# Channels that ship with subtype_split=True in v0.3.7-pre defaults.
KEEP_SUBTYPES_FOR = {"agents"}


def find_orphans(sesslogs_root: Path, include_legacy_overflows: bool = False) -> list[Path]:
    """Walk every session dir top level; return paths of files to clean up.

    Always returns subtype-derived files (e.g., `.sesslog-bash_*`,
    `.tools-grep_*`) for channels NOT in KEEP_SUBTYPES_FOR.

    If `include_legacy_overflows` is True, also returns legacy
    `.overflow.N` files (pre-#47 cruft from dormant sessions whose
    SessionLogger never ran the in-process migrate_overflow_files).

    Skips bak/baks dirs, transcript symlinks, and sentinel markers.
    """
    orphans: list[Path] = []
    if not sesslogs_root.exists():
        return orphans
    for session_dir in sesslogs_root.iterdir():
        if not session_dir.is_dir():
            continue
        if session_dir.name in ("bak", "baks"):
            continue
        for f in session_dir.iterdir():
            if not f.is_file():
                continue
            # Skip transcript symlink and sentinel files
            if f.name in ("transcript.jsonl",):
                continue
            if (f.name.startswith(".session-logger-")
                or f.name == "README.session-logger.md"
                or f.name.startswith(".overflow_migrated_")
                or f.name.startswith(".orphan_session_name_swept_")):
                continue  # state markers + docs, including legacy names
            # Legacy .overflow.N files (pre-#47, dormant sessions)
            if include_legacy_overflows and LEGACY_OVERFLOW_PATTERN.search(f.name):
                orphans.append(f)
                continue
            # Subtype-derived files
            match = SUBTYPE_PATTERN.match(f.name)
            if not match:
                continue  # Base channel file, no `-<subtype>` segment
            channel_basename = match.group(1)
            if channel_basename in KEEP_SUBTYPES_FOR:
                continue  # `.agents-*` stays
            orphans.append(f)
    return orphans


def move_to_bak(orphan: Path, sesslogs_root: Path) -> Path:
    """Move `orphan` to <sesslogs_root>/bak/<session-dir-name>/<filename>.
    Numeric suffix on collision. Returns the destination path."""
    session_dir = orphan.parent
    dest_dir = sesslogs_root / "bak" / session_dir.name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / orphan.name
    i = 1
    while dest.exists():
        dest = dest_dir / f"{orphan.name}.{i}"
        i += 1
    shutil.move(str(orphan), str(dest))
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move files. Without this flag, only prints what would happen.",
    )
    parser.add_argument(
        "--sesslogs-root",
        default=str(Path.home() / ".claude" / "sesslogs"),
        help="Root of session logs (default: ~/.claude/sesslogs)",
    )
    parser.add_argument(
        "--include-legacy-overflows",
        action="store_true",
        help=(
            "Also clean up legacy .overflow.N files in dormant session dirs "
            "(pre-#47 cruft whose SessionLogger never ran the in-process "
            "migrate_overflow_files). Moves them to <bak>/<session-dir>/."
        ),
    )
    args = parser.parse_args()

    sesslogs_root = Path(args.sesslogs_root)
    orphans = find_orphans(sesslogs_root, include_legacy_overflows=args.include_legacy_overflows)

    if not orphans:
        print(f"No subtype-derived orphan files found under {sesslogs_root}")
        return 0

    # Group by session dir for clearer reporting
    by_session: dict[str, list[Path]] = {}
    for f in orphans:
        by_session.setdefault(f.parent.name, []).append(f)

    total = len(orphans)
    print(f"{'WOULD MOVE' if not args.apply else 'MOVING'} {total} file(s) "
          f"across {len(by_session)} session(s):")
    for session_name in sorted(by_session):
        files = by_session[session_name]
        print(f"\n  {session_name}/  ({len(files)} file{'s' if len(files) != 1 else ''}):")
        for f in sorted(files):
            print(f"    {f.name}")

    if not args.apply:
        print(f"\nDestination would be: {sesslogs_root / 'bak' / '<session-dir-name>/'}")
        print("Re-run with --apply to perform the moves.")
        return 0

    moved = 0
    for f in orphans:
        try:
            dest = move_to_bak(f, sesslogs_root)
            moved += 1
        except OSError as e:
            print(f"  FAILED to move {f.name}: {e}", file=sys.stderr)
    print(f"\nMoved {moved}/{total} file(s) to {sesslogs_root / 'bak'}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
