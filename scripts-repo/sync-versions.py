#!/usr/bin/env python3
"""
Synchronize version numbers across all project files.

Reads the canonical version from version.py (MAJOR, MINOR, PATCH) and updates:
- .claude-plugin/plugin.json
- .claude-plugin/marketplace.json
- Optionally calls update-version.sh to sync __version__ string

Usage:
    python scripts-repo/sync-versions.py [OPTIONS]

Options:
    --check         Only check if versions are in sync (don't modify)
    --bump PART     Bump version before syncing (major, minor, patch)
    --dry-run       Show what would change without modifying files
    --no-git-ver    Skip calling update-version.sh
    --verbose       Show detailed output
    --dev-refresh   Clear plugin cache and reinstall (for development testing)

Examples:
    # Check sync status
    python scripts-repo/sync-versions.py --check

    # Bump patch version and sync everything
    python scripts-repo/sync-versions.py --bump patch

    # Sync without updating git version string
    python scripts-repo/sync-versions.py --no-git-ver

    # Development: bump version, clear cache, reinstall plugin
    python scripts-repo/sync-versions.py --bump patch --dev-refresh
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# Files to update (relative to project root)
VERSION_SOURCE = "version.py"
VERSION_TARGETS = [
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
]
UPDATE_VERSION_SCRIPT = "scripts-repo/update-version.sh"

# Plugin info for --dev-refresh
PLUGIN_NAME = "session-logger@dazzle-claude-plugins"
PLUGIN_CACHE_PATH = Path.home() / ".claude" / "plugins" / "cache" / "dazzle-claude-plugins" / "session-logger"


def find_project_root() -> Path:
    """Find project root by looking for version.py."""
    # Try current directory
    if Path(VERSION_SOURCE).exists():
        return Path.cwd()
    # Try parent (if running from scripts-repo)
    parent = Path.cwd().parent
    if (parent / VERSION_SOURCE).exists():
        return parent
    raise FileNotFoundError(f"Cannot find {VERSION_SOURCE}. Run from project root.")


def read_version_py(root: Path) -> tuple[int, int, int, str | None]:
    """Read MAJOR, MINOR, PATCH, PHASE from version.py."""
    version_file = root / VERSION_SOURCE
    content = version_file.read_text(encoding='utf-8')

    major = re.search(r'^MAJOR\s*=\s*(\d+)', content, re.MULTILINE)
    minor = re.search(r'^MINOR\s*=\s*(\d+)', content, re.MULTILINE)
    patch = re.search(r'^PATCH\s*=\s*(\d+)', content, re.MULTILINE)

    if not all([major, minor, patch]):
        raise ValueError("Could not parse MAJOR, MINOR, PATCH from version.py")

    # Parse PHASE - can be None, "alpha", "beta", "rc1", etc.
    phase_match = re.search(r'^PHASE\s*=\s*(.+)$', content, re.MULTILINE)
    phase = None
    if phase_match:
        phase_value = phase_match.group(1).strip()
        # Handle None, "None", quoted strings like "alpha" or 'beta'
        if phase_value in ('None', 'none', 'null', '""', "''"):
            phase = None
        else:
            # Strip quotes and comments
            phase_value = re.sub(r'#.*$', '', phase_value).strip()
            phase_value = phase_value.strip('"\'')
            if phase_value and phase_value.lower() not in ('none', 'null'):
                phase = phase_value

    return int(major.group(1)), int(minor.group(1)), int(patch.group(1)), phase


def write_version_py(root: Path, major: int, minor: int, patch: int, phase: str | None = None,
                     update_phase: bool = False) -> None:
    """Update MAJOR, MINOR, PATCH, and optionally PHASE in version.py."""
    version_file = root / VERSION_SOURCE
    content = version_file.read_text(encoding='utf-8')

    content = re.sub(r'^(MAJOR\s*=\s*)\d+', f'\\g<1>{major}', content, flags=re.MULTILINE)
    content = re.sub(r'^(MINOR\s*=\s*)\d+', f'\\g<1>{minor}', content, flags=re.MULTILINE)
    content = re.sub(r'^(PATCH\s*=\s*)\d+', f'\\g<1>{patch}', content, flags=re.MULTILINE)

    # Update PHASE if requested
    if update_phase:
        if phase:
            phase_str = f'"{phase}"'
        else:
            phase_str = 'None'
        content = re.sub(r'^(PHASE\s*=\s*).*$', f'\\g<1>{phase_str}', content, flags=re.MULTILINE)

    version_file.write_text(content, encoding='utf-8')


def format_version_string(major: int, minor: int, patch: int, phase: str | None = None) -> str:
    """Format version as string, including phase if present."""
    base = f"{major}.{minor}.{patch}"
    if phase:
        return f"{base}-{phase}"
    return base


def read_json_version(file_path: Path) -> list[str]:
    """Read all version strings from a JSON file."""
    content = file_path.read_text(encoding='utf-8')
    versions = re.findall(r'"version"\s*:\s*"([^"]+)"', content)
    return versions


def update_json_version(file_path: Path, new_version: str, dry_run: bool = False) -> bool:
    """Update all version strings in a JSON file."""
    content = file_path.read_text(encoding='utf-8')
    original = content

    # Update all "version": "x.x.x" occurrences
    content = re.sub(
        r'("version"\s*:\s*")[^"]+(")',
        f'\\g<1>{new_version}\\g<2>',
        content
    )

    if content != original:
        if not dry_run:
            file_path.write_text(content, encoding='utf-8')
        return True
    return False


def check_changelog(root: Path, version: str) -> bool:
    """Check if CHANGELOG.md has an entry for this version."""
    changelog = root / "CHANGELOG.md"
    if not changelog.exists():
        return False

    content = changelog.read_text(encoding='utf-8')
    pattern = rf'##\s*\[{re.escape(version)}\]'
    return bool(re.search(pattern, content))


def bump_version(major: int, minor: int, patch: int, part: str) -> tuple[int, int, int]:
    """Bump (increment) the specified version part."""
    if part == "major":
        return major + 1, 0, 0
    elif part == "minor":
        return major, minor + 1, 0
    elif part == "patch":
        return major, minor, patch + 1
    else:
        raise ValueError(f"Unknown version part: {part}")


def demote_version(major: int, minor: int, patch: int, part: str) -> tuple[int, int, int]:
    """Demote (decrement) the specified version part. Inverse of bump."""
    if part == "major":
        if major <= 0:
            raise ValueError(f"Cannot demote major below 0 (current: {major}.{minor}.{patch})")
        return major - 1, 0, 0
    elif part == "minor":
        if minor <= 0:
            raise ValueError(f"Cannot demote minor below 0 (current: {major}.{minor}.{patch})")
        return major, minor - 1, 0
    elif part == "patch":
        if patch <= 0:
            raise ValueError(f"Cannot demote patch below 0 (current: {major}.{minor}.{patch})")
        return major, minor, patch - 1
    else:
        raise ValueError(f"Unknown version part: {part}")


def parse_version_string(version_str: str) -> tuple[int, int, int]:
    """Parse a version string like '0.2.3' into (major, minor, patch)."""
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)$', version_str.strip())
    if not match:
        raise ValueError(f"Invalid version format: '{version_str}'. Expected X.Y.Z (e.g., 0.2.0)")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def run_update_version_sh(root: Path, dry_run: bool = False, verbose: bool = False) -> bool:
    """Run update-version.sh to sync the __version__ string."""
    script_path = root / UPDATE_VERSION_SCRIPT

    if not script_path.exists():
        print(f"  Warning: {UPDATE_VERSION_SCRIPT} not found, skipping git version update")
        return False

    if dry_run:
        print(f"  [DRY] Would run: {UPDATE_VERSION_SCRIPT}")
        return True

    try:
        # Determine how to run the script
        if os.name == 'nt':
            # Windows - try bash from Git for Windows or WSL
            bash_paths = [
                "C:/Program Files/Git/bin/bash.exe",
                "C:/Program Files (x86)/Git/bin/bash.exe",
                "bash",  # WSL or Git Bash in PATH
            ]
            bash_cmd = None
            for bp in bash_paths:
                try:
                    subprocess.run([bp, "--version"], capture_output=True, check=True)
                    bash_cmd = bp
                    break
                except (subprocess.CalledProcessError, FileNotFoundError):
                    continue

            if bash_cmd:
                cmd = [bash_cmd, str(script_path)]
            else:
                print("  Warning: No bash found, skipping update-version.sh")
                return False
        else:
            # Unix - run directly
            cmd = [str(script_path)]

        if verbose:
            print(f"  Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            if verbose and result.stdout:
                for line in result.stdout.strip().split('\n'):
                    print(f"    {line}")
            return True
        else:
            print(f"  Warning: update-version.sh failed: {result.stderr}")
            return False

    except Exception as e:
        print(f"  Warning: Could not run update-version.sh: {e}")
        return False


def clear_plugin_cache_version(version: str, dry_run: bool = False, force: bool = False) -> bool:
    """Remove a specific version from the plugin cache.

    Args:
        version: Version string to remove (e.g., "0.1.6")
        dry_run: If True, only show what would be done
        force: If True, skip confirmation prompt
    """
    cache_version_path = PLUGIN_CACHE_PATH / version

    if not cache_version_path.exists():
        print(f"  Cache {version}/ does not exist (nothing to clear)")
        return True

    # Show what will be deleted
    print(f"\n  Plugin cache to remove:")
    print(f"    Path: {cache_version_path}")

    # Count contents for visibility
    try:
        file_count = sum(1 for _ in cache_version_path.rglob("*") if _.is_file())
        print(f"    Contains: {file_count} file(s)")
    except Exception:
        pass

    if dry_run:
        print(f"  [DRY] Would remove this directory")
        return True

    # Require confirmation unless --force
    if not force:
        try:
            confirm = input(f"\n  Delete {cache_version_path}? [y/N]: ")
            if confirm.lower() not in ('y', 'yes'):
                print("  Skipped (no confirmation)")
                return False
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipped (interrupted)")
            return False

    try:
        shutil.rmtree(cache_version_path)
        print(f"  Cleared cache: {version}/")
        return True
    except Exception as e:
        print(f"  Warning: Could not remove cache {version}/: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Sync versions across project files")
    parser.add_argument("--check", action="store_true", help="Only check, don't modify")
    parser.add_argument("--bump", choices=["major", "minor", "patch"], help="Bump (increment) version part")
    parser.add_argument("--demote", choices=["major", "minor", "patch"], help="Demote (decrement) version part")
    parser.add_argument("--set", metavar="X.Y.Z", help="Set version directly (e.g., --set 0.2.0)")
    parser.add_argument("--phase", metavar="PHASE", help="Set release phase (alpha, beta, rc1) or 'none' to clear")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without modifying")
    parser.add_argument("--no-git-ver", action="store_true", help="Skip update-version.sh")
    parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation for major changes")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--dev-refresh", nargs="*", default=None, metavar="VERSION",
                        help="Clear version(s) from plugin cache. Without args: clears target version. With args: clears specified version(s) (e.g., --dev-refresh 0.1.5 0.1.6)")
    args = parser.parse_args()

    try:
        root = find_project_root()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Read current version
    major, minor, patch, phase = read_version_py(root)
    current_version = format_version_string(major, minor, patch, phase)
    update_phase = False  # Track if we need to update PHASE in version.py

    # Handle --phase argument
    if args.phase:
        update_phase = True
        if args.phase.lower() in ('none', 'null', 'stable', 'release', ''):
            phase = None
        else:
            phase = args.phase

    if args.verbose:
        print(f"Project root: {root}")
        print(f"Source: {VERSION_SOURCE}")
        if phase:
            print(f"Phase: {phase}")

    # Handle --set, --bump, or --demote (mutually exclusive)
    version_ops = [args.set, args.bump, args.demote]
    if sum(1 for op in version_ops if op) > 1:
        print("Error: Cannot use --set, --bump, and --demote together", file=sys.stderr)
        return 1

    if args.set:
        try:
            new_major, new_minor, new_patch = parse_version_string(args.set)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        new_version = format_version_string(new_major, new_minor, new_patch, phase)

        # Require confirmation for major version changes (unless --force or --dry-run)
        if new_major != major and not args.force and not args.dry_run and not args.check:
            print(f"\n  WARNING: Major version change: {current_version} -> {new_version}")
            try:
                confirm = input("\n  Type 'yes' to confirm: ")
                if confirm.lower() != 'yes':
                    print("  Aborted.")
                    return 1
            except (EOFError, KeyboardInterrupt):
                print("\n  Aborted.")
                return 1

        print(f"Setting version: {current_version} -> {new_version}")

        if not args.check and not args.dry_run:
            write_version_py(root, new_major, new_minor, new_patch, phase, update_phase)

        major, minor, patch = new_major, new_minor, new_patch
        current_version = new_version

    elif args.bump:
        new_major, new_minor, new_patch = bump_version(major, minor, patch, args.bump)
        new_version = format_version_string(new_major, new_minor, new_patch, phase)

        # Require confirmation for major version bumps (unless --force or --dry-run)
        if args.bump == "major" and not args.force and not args.dry_run and not args.check:
            print(f"\n  WARNING: Major version bump will change {current_version} -> {new_version}")
            print(f"           This resets minor and patch to 0.")
            try:
                confirm = input("\n  Type 'yes' to confirm: ")
                if confirm.lower() != 'yes':
                    print("  Aborted.")
                    return 1
            except (EOFError, KeyboardInterrupt):
                print("\n  Aborted.")
                return 1

        print(f"Bumping {args.bump}: {current_version} -> {new_version}")

        if not args.check and not args.dry_run:
            write_version_py(root, new_major, new_minor, new_patch, phase, update_phase)

        major, minor, patch = new_major, new_minor, new_patch
        current_version = new_version

    elif args.demote:
        try:
            new_major, new_minor, new_patch = demote_version(major, minor, patch, args.demote)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        new_version = format_version_string(new_major, new_minor, new_patch, phase)

        # Require confirmation for major version demotes (unless --force or --dry-run)
        if args.demote == "major" and not args.force and not args.dry_run and not args.check:
            print(f"\n  WARNING: Major version demote will change {current_version} -> {new_version}")
            print(f"           This resets minor and patch to 0.")
            try:
                confirm = input("\n  Type 'yes' to confirm: ")
                if confirm.lower() != 'yes':
                    print("  Aborted.")
                    return 1
            except (EOFError, KeyboardInterrupt):
                print("\n  Aborted.")
                return 1

        print(f"Demoting {args.demote}: {current_version} -> {new_version}")

        if not args.check and not args.dry_run:
            write_version_py(root, new_major, new_minor, new_patch, phase, update_phase)

        major, minor, patch = new_major, new_minor, new_patch
        current_version = new_version

    elif update_phase:
        # Phase-only change (no version bump/set/demote)
        new_version = format_version_string(major, minor, patch, phase)
        print(f"Setting phase: {current_version} -> {new_version}")

        if not args.check and not args.dry_run:
            write_version_py(root, major, minor, patch, phase, update_phase)

        current_version = new_version

    print(f"Version: {current_version}")

    # Track status
    all_synced = True
    files_updated = []

    # Check/update each target file
    for target in VERSION_TARGETS:
        target_path = root / target
        if not target_path.exists():
            print(f"  Warning: {target} not found")
            continue

        versions = read_json_version(target_path)
        needs_update = any(v != current_version for v in versions)

        if needs_update:
            all_synced = False
            if args.check:
                print(f"  [X] {target}: {versions} (expected {current_version})")
            else:
                updated = update_json_version(target_path, current_version, args.dry_run)
                if updated:
                    action = "would update" if args.dry_run else "updated"
                    print(f"  [OK] {target}: {action} to {current_version}")
                    files_updated.append(target)
        else:
            if args.verbose:
                print(f"  [OK] {target}: {current_version}")

    # Run update-version.sh to sync __version__ string (unless --no-git-ver)
    if not args.check and not args.no_git_ver:
        print("\nUpdating git version string...")
        run_update_version_sh(root, args.dry_run, args.verbose)

    # Clear plugin cache (--dev-refresh)
    # args.dev_refresh is None (not used), [] (used without args), or [list of versions]
    if args.dev_refresh is not None and not args.check:
        version_changed = args.set or args.bump or args.demote
        target_version = f"{major}.{minor}.{patch}"
        cleared_versions = set()

        if not args.dev_refresh:
            # No explicit versions - clear target (or current if no version change)
            clear_plugin_cache_version(target_version, args.dry_run, args.force)
            cleared_versions.add(target_version)
        else:
            # Explicit version(s) specified
            for explicit_version in args.dev_refresh:
                if explicit_version not in cleared_versions:
                    clear_plugin_cache_version(explicit_version, args.dry_run, args.force)
                    cleared_versions.add(explicit_version)

            # If version is changing, also check target version (if not already cleared)
            if version_changed and target_version not in cleared_versions:
                cache_path = PLUGIN_CACHE_PATH / target_version
                if cache_path.exists():
                    print(f"\n  Note: Target version {target_version} also has cached data")
                    clear_plugin_cache_version(target_version, args.dry_run, args.force)
                    cleared_versions.add(target_version)

    # Check CHANGELOG
    if not check_changelog(root, current_version):
        print(f"\n  Note: No CHANGELOG.md entry found for [{current_version}]")

    # Summary
    if args.check:
        if all_synced:
            print("\nAll versions are in sync.")
            return 0
        else:
            print("\nVersions are out of sync. Run without --check to fix.")
            return 1
    elif files_updated:
        if args.dry_run:
            print(f"\nDry run: would update {len(files_updated)} file(s)")
        else:
            print(f"\nUpdated {len(files_updated)} file(s)")
    else:
        print("\nAll versions already in sync.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
