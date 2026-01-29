#!/usr/bin/env python3
"""
Install claude-session-logger hooks and commands to ~/.claude/

Usage:
    python install.py           # Install to ~/.claude/
    python install.py --check   # Check what would be installed
    python install.py --force   # Overwrite existing files
"""

import argparse
import shutil
import sys
from pathlib import Path


def get_claude_dir() -> Path:
    """Get the ~/.claude directory path."""
    return Path.home() / ".claude"


def install(check_only: bool = False, force: bool = False) -> bool:
    """Install hooks and commands to ~/.claude/"""

    script_dir = Path(__file__).parent
    claude_dir = get_claude_dir()

    # Files to install
    files = [
        ("claude/hooks/log-command.py", "hooks/log-command.py"),
        ("claude/hooks/rename_session.py", "hooks/rename_session.py"),
        ("claude/commands/renameAI.md", "commands/renameAI.md"),
        ("claude/commands/sessioninfo.md", "commands/sessioninfo.md"),
    ]

    print(f"Claude directory: {claude_dir}")
    print()

    if check_only:
        print("Files to install:")
        for src_rel, dst_rel in files:
            src = script_dir / src_rel
            dst = claude_dir / dst_rel
            exists = dst.exists()
            status = " (exists, will skip)" if exists and not force else ""
            status = " (exists, will overwrite)" if exists and force else status
            print(f"  {src_rel} -> {dst_rel}{status}")
        print()
        print("Run without --check to install.")
        return True

    # Create directories
    (claude_dir / "hooks").mkdir(parents=True, exist_ok=True)
    (claude_dir / "commands").mkdir(parents=True, exist_ok=True)

    installed = 0
    skipped = 0

    for src_rel, dst_rel in files:
        src = script_dir / src_rel
        dst = claude_dir / dst_rel

        if not src.exists():
            print(f"  ERROR: Source file not found: {src}")
            continue

        if dst.exists() and not force:
            print(f"  SKIP: {dst_rel} (exists, use --force to overwrite)")
            skipped += 1
            continue

        shutil.copy2(src, dst)
        print(f"  OK: {dst_rel}")
        installed += 1

    print()
    print(f"Installed: {installed}, Skipped: {skipped}")

    if installed > 0:
        print()
        print("Next steps:")
        print("  1. Add hooks to ~/.claude/settings.json (see README.md)")
        print("  2. Optionally install dazzle-filekit: pip install dazzle-filekit")
        print("  3. Restart Claude Code")

    return True


def main():
    parser = argparse.ArgumentParser(description="Install claude-session-logger")
    parser.add_argument("--check", action="store_true", help="Check what would be installed")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    try:
        success = install(check_only=args.check, force=args.force)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
