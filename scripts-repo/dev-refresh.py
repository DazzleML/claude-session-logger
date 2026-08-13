#!/usr/bin/env python3
"""
Clear the Claude Code plugin cache for this plugin during development.

When developing a Claude Code plugin, every install lands at:
    ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/

If you bump from 0.1.10 -> 0.1.11 and reinstall, Claude Code may serve the
old 0.1.10/ cache (or a stale 0.1.11/ if you previously installed and then
made local changes). This script deletes the named version directory so the
next `claude plugin install` writes fresh files.

This is project-specific (Claude-Code-plugin) and does NOT belong in the
upstream git-repokit-common scripts-repo/. It lives in scripts-repo/local/
where project-specific tooling is the convention.

History: ported from scripts-repo_bak/sync-versions.py's --dev-refresh
flag (commit a9b0ed0 era). Standalone script now because (a) sync-versions.py
generalized via extra-targets covers the version-bump side, and (b) keeping
the cache-clear logic separate avoids cluttering upstream sync-versions.py
with plugin-host-specific behavior.

Usage:
    python scripts-repo/local/dev-refresh.py                 # clear current version (from version.py)
    python scripts-repo/local/dev-refresh.py 0.1.5 0.1.6     # clear specific versions
    python scripts-repo/local/dev-refresh.py --dry-run       # preview only
    python scripts-repo/local/dev-refresh.py --force         # skip confirmation prompt
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


# Project-specific: this is the cache path for THIS plugin under the
# DazzleML marketplace namespace. If the plugin moves marketplaces or
# Claude Code changes its caching scheme, update these constants.
PLUGIN_NAME = "session-logger@dazzle-claude-plugins"
PLUGIN_CACHE_PATH = (
    Path.home() / ".claude" / "plugins" / "cache" / "dazzle-claude-plugins" / "session-logger"
)
VERSION_SOURCE = "version.py"


def find_repo_root(start: Path) -> Path:
    """Walk up from start looking for the version source file."""
    cur = start.resolve()
    for _ in range(8):
        if (cur / VERSION_SOURCE).exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise FileNotFoundError(
        f"Could not find {VERSION_SOURCE} walking up from {start}"
    )


def read_current_version(root: Path) -> str:
    """Read MAJOR.MINOR.PATCH from version.py."""
    content = (root / VERSION_SOURCE).read_text(encoding="utf-8")
    major = re.search(r"^MAJOR\s*=\s*(\d+)", content, re.MULTILINE)
    minor = re.search(r"^MINOR\s*=\s*(\d+)", content, re.MULTILINE)
    patch = re.search(r"^PATCH\s*=\s*(\d+)", content, re.MULTILINE)
    if not all([major, minor, patch]):
        raise ValueError(f"Could not parse MAJOR/MINOR/PATCH from {VERSION_SOURCE}")
    return f"{major.group(1)}.{minor.group(1)}.{patch.group(1)}"


def clear_version(version: str, dry_run: bool, force: bool) -> int:
    """Remove a single version's cache directory.

    Returns: 0 on success or "nothing to clear", non-zero on failure.
    """
    cache_version_path = PLUGIN_CACHE_PATH / version

    if not cache_version_path.exists():
        print(f"  Cache {version}/ does not exist (nothing to clear)")
        return 0

    print(f"\n  Plugin cache to remove:")
    print(f"    Path: {cache_version_path}")

    try:
        file_count = sum(1 for _ in cache_version_path.rglob("*") if _.is_file())
        print(f"    Contains: {file_count} file(s)")
    except Exception:
        pass

    if dry_run:
        print(f"  [DRY] Would remove this directory")
        return 0

    if not force:
        try:
            confirm = input(f"\n  Delete {cache_version_path}? [y/N]: ")
            if confirm.lower() not in ("y", "yes"):
                print("  Skipped (no confirmation)")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipped (interrupted)")
            return 0

    try:
        shutil.rmtree(cache_version_path)
        print(f"  Cleared cache: {version}/")
        return 0
    except Exception as e:
        print(f"  Warning: Could not remove cache {version}/: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clear the Claude Code plugin cache for this plugin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "versions",
        nargs="*",
        help="Versions to clear (e.g., 0.1.5 0.1.6). If omitted, clears the current version from version.py.",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without removing anything",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Skip confirmation prompts",
    )
    args = parser.parse_args()

    try:
        root = find_repo_root(Path.cwd())
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.versions:
        target_versions = args.versions
    else:
        try:
            target_versions = [read_current_version(root)]
        except (ValueError, OSError) as e:
            print(f"Error reading current version: {e}", file=sys.stderr)
            return 1

    print(f"Plugin: {PLUGIN_NAME}")
    print(f"Cache root: {PLUGIN_CACHE_PATH}")
    print(f"Versions to clear: {', '.join(target_versions)}")

    overall = 0
    for v in target_versions:
        rc = clear_version(v, args.dry_run, args.force)
        if rc != 0:
            overall = rc

    if overall == 0 and not args.dry_run:
        print("\nDone. Reinstall the plugin to pull fresh files:")
        print(f"  claude plugin install {PLUGIN_NAME}")

    return overall


if __name__ == "__main__":
    sys.exit(main())
