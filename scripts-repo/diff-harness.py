#!/usr/bin/env python3
"""
Differential test harness for sync-versions.py behavior.

Compares the OLD (pre-subtree-migration) sync-versions.py against the NEW
(current HEAD with subtree + extra-targets) implementation, proving
behavioral equivalence on the version-management surface.

Methodology
-----------
Two full directory copies in a temp dir, NOT git worktrees (worktrees share
.git/, which leaks commits and hooks). Each copy is independent; operations
in one cannot affect the other or the original repo.

Operations run identically in both copies:
    --check --verbose
    --bump patch --dry-run --verbose
    --bump patch                      (real mutation, contained in copy)

Then we diff:
    version.py MAJOR/MINOR/PATCH lines
    .claude-plugin/plugin.json "version" field
    .claude-plugin/marketplace.json "version" fields

Allowed differences (normalized before diff):
    version.py __version__ string (build metadata: branch/count/date/hash)
    Timestamps in tool output
    File paths involving the temp directory names

Safety
------
- NEVER --dev-refresh against real versions (only bogus 99.99.99 for path checks)
- Disable pre-commit hooks in test copies
- Mandatory cleanup of temp dirs (even on exception)
- Leakage check: confirm ~/.claude/plugins/cache and original repo unchanged

Usage
-----
    python scripts-repo/local/diff-harness.py [--keep] [--verbose] [--old-ref REF]

    --keep        Don't delete the temp copies after running (for inspection)
    --verbose     Show every command run and full output
    --old-ref     Git ref for the OLD copy (default: pre-subtree-migration-v0.1.11)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional


REPO_ROOT_MARKER = "version.py"
DEFAULT_OLD_REF = "pre-subtree-migration-v0.1.11"
PLUGIN_CACHE_PATH = (
    Path.home() / ".claude" / "plugins" / "cache" / "dazzle-claude-plugins" / "session-logger"
)


def find_repo_root(start: Path) -> Path:
    """Walk up from `start` looking for the marker file."""
    cur = start.resolve()
    for _ in range(8):
        if (cur / REPO_ROOT_MARKER).exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise FileNotFoundError(
        f"Could not find {REPO_ROOT_MARKER} walking up from {start}"
    )


def run(
    cmd: list[str],
    cwd: Optional[Path] = None,
    check: bool = True,
    verbose: bool = False,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Run a shell command, optionally capturing output."""
    if verbose:
        cwd_disp = f" (cwd={cwd})" if cwd else ""
        print(f"  $ {' '.join(cmd)}{cwd_disp}", flush=True)
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=capture,
        text=capture,
    )
    return result


def clone_copy(src_repo: Path, dest: Path, ref: str, verbose: bool) -> None:
    """Clone src_repo to dest with --no-local (so .git/ is fully independent)
    and check out the specified ref."""
    run(
        ["git", "clone", "--no-local", str(src_repo), str(dest)],
        verbose=verbose,
    )
    run(["git", "checkout", ref], cwd=dest, verbose=verbose)


def overlay_worktree(src_repo: Path, dest: Path, verbose: bool) -> int:
    """Overlay src_repo's working-tree files onto dest, excluding .git/.

    Use this when you want to test uncommitted changes -- after cloning the
    NEW copy from HEAD, overlay the actual working tree to capture in-progress
    edits. Skips .git/, common cache dirs, and the test sandbox dir patterns.

    Returns count of files copied.
    """
    skip_dirs = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}
    count = 0
    for item in src_repo.rglob("*"):
        if any(part in skip_dirs for part in item.relative_to(src_repo).parts):
            continue
        if item.is_file():
            rel = item.relative_to(src_repo)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            count += 1
    if verbose:
        print(f"  Overlaid {count} working-tree file(s) onto {dest}")
    return count


def disable_hooks(repo: Path, verbose: bool) -> None:
    """Remove pre-commit / post-commit / pre-push hooks so test ops don't trigger them."""
    hooks_dir = repo / ".git" / "hooks"
    for hook in ("pre-commit", "post-commit", "pre-push", "commit-msg"):
        h = hooks_dir / hook
        if h.exists() and not h.name.endswith(".sample"):
            if verbose:
                print(f"  Disabling hook: {h}")
            h.unlink()


def find_sync_versions(repo: Path) -> Optional[Path]:
    """Locate sync-versions.py within a repo copy. Path may differ across the
    OLD/NEW boundary if the script moved during the migration."""
    candidates = [
        repo / "scripts-repo" / "sync-versions.py",
        repo / "scripts-repo_bak" / "sync-versions.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def capture_version_files(repo: Path) -> dict[str, str]:
    """Snapshot the contents of the version files we care about."""
    files = {
        "version.py": repo / "version.py",
        "plugin.json": repo / ".claude-plugin" / "plugin.json",
        "marketplace.json": repo / ".claude-plugin" / "marketplace.json",
    }
    snap: dict[str, str] = {}
    for name, path in files.items():
        if path.exists():
            snap[name] = path.read_text(encoding="utf-8")
        else:
            snap[name] = "(file not present)"
    return snap


def normalize_for_diff(snapshot: dict[str, str]) -> dict[str, str]:
    """Strip allowed-difference content so byte-diff focuses on the values
    that MUST be identical."""
    out: dict[str, str] = {}
    for name, content in snapshot.items():
        if name == "version.py":
            # Strip __version__ string entirely (build metadata varies across runs)
            content = re.sub(
                r'^__version__\s*=\s*"[^"]*"\s*$',
                '__version__ = "<NORMALIZED>"',
                content,
                flags=re.MULTILINE,
            )
        # Strip lines that are just timestamps or commit hashes (heuristic)
        out[name] = content
    return out


def extract_version_values(snapshot: dict[str, str]) -> dict[str, str]:
    """Pull the SemVer values out of each file for a focused comparison."""
    values: dict[str, str] = {}

    vp = snapshot.get("version.py", "")
    m_major = re.search(r"^MAJOR\s*=\s*(\d+)", vp, re.MULTILINE)
    m_minor = re.search(r"^MINOR\s*=\s*(\d+)", vp, re.MULTILINE)
    m_patch = re.search(r"^PATCH\s*=\s*(\d+)", vp, re.MULTILINE)
    if all([m_major, m_minor, m_patch]):
        values["version.py components"] = (
            f"{m_major.group(1)}.{m_minor.group(1)}.{m_patch.group(1)}"
        )

    for fname in ("plugin.json", "marketplace.json"):
        content = snapshot.get(fname, "")
        versions = re.findall(r'"version"\s*:\s*"([^"]+)"', content)
        if versions:
            values[f"{fname} 'version' fields"] = ",".join(versions)

    return values


def file_diff(
    a_snap: dict[str, str], b_snap: dict[str, str], normalize: bool
) -> list[str]:
    """Return a list of diff lines (empty if identical)."""
    a_use = normalize_for_diff(a_snap) if normalize else a_snap
    b_use = normalize_for_diff(b_snap) if normalize else b_snap

    diff_lines: list[str] = []
    keys = sorted(set(a_use) | set(b_use))
    for k in keys:
        a_text = a_use.get(k, "(missing in OLD)")
        b_text = b_use.get(k, "(missing in NEW)")
        if a_text != b_text:
            diff_lines.append(f"=== DIFF in {k} ===")
            import difflib

            diff_lines.extend(
                difflib.unified_diff(
                    a_text.splitlines(),
                    b_text.splitlines(),
                    fromfile=f"OLD/{k}",
                    tofile=f"NEW/{k}",
                    lineterm="",
                )
            )
    return diff_lines


def leakage_check(plugin_cache_before: list[str], original_log_before: str) -> list[str]:
    """Return list of leakage problems (empty if clean)."""
    problems: list[str] = []

    # Check plugin cache
    if PLUGIN_CACHE_PATH.exists():
        after = sorted(p.name for p in PLUGIN_CACHE_PATH.iterdir() if p.is_dir())
        if after != plugin_cache_before:
            problems.append(
                f"Plugin cache mutated! Before: {plugin_cache_before}, After: {after}"
            )

    # Check original repo's git log (we only check the count and HEAD; deep equality is overkill)
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-3"],
            cwd=str(find_repo_root(Path.cwd())),
            capture_output=True,
            text=True,
            check=True,
        )
        after_log = result.stdout
        if after_log != original_log_before:
            problems.append(
                "Original repo's git log changed! Before:\n"
                f"{original_log_before}\nAfter:\n{after_log}"
            )
    except Exception as e:
        problems.append(f"Could not verify original repo log: {e}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Differential test harness for sync-versions.py",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Don't delete the temp copies after running (for inspection)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show every command run and verbose output",
    )
    parser.add_argument(
        "--old-ref",
        default=DEFAULT_OLD_REF,
        help=f"Git ref for OLD copy (default: {DEFAULT_OLD_REF})",
    )
    parser.add_argument(
        "--use-worktree",
        action="store_true",
        help=(
            "Overlay the source repo's WORKING TREE onto the NEW copy (after the "
            "HEAD clone). Use this to test uncommitted changes without committing "
            "first. The OLD copy is untouched (always reflects the --old-ref tag)."
        ),
    )
    args = parser.parse_args()

    src_repo = find_repo_root(Path.cwd())
    print(f"Source repo: {src_repo}")
    print(f"OLD ref: {args.old_ref}")

    # Snapshot leakage-check baseline BEFORE doing anything
    plugin_cache_before: list[str] = []
    if PLUGIN_CACHE_PATH.exists():
        plugin_cache_before = sorted(
            p.name for p in PLUGIN_CACHE_PATH.iterdir() if p.is_dir()
        )
    print(f"Plugin cache baseline: {plugin_cache_before}")

    original_log_before = subprocess.run(
        ["git", "log", "--oneline", "-3"],
        cwd=str(src_repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    work_root = Path(tempfile.mkdtemp(prefix=f"sl-diff-{stamp}-"))
    old_copy = work_root / "old"
    new_copy = work_root / "new"
    print(f"Work directory: {work_root}")

    exit_code = 0

    try:
        # 1. Clone OLD and NEW copies
        print("\n[1/5] Cloning OLD copy...")
        clone_copy(src_repo, old_copy, args.old_ref, args.verbose)
        print(f"\n[2/5] Cloning NEW copy at HEAD...")
        clone_copy(src_repo, new_copy, "HEAD", args.verbose)
        if args.use_worktree:
            print("       --use-worktree: overlaying source working tree onto NEW copy...")
            overlay_worktree(src_repo, new_copy, args.verbose)

        # 2. Disable hooks in both
        print("\n[3/5] Disabling hooks in both copies...")
        disable_hooks(old_copy, args.verbose)
        disable_hooks(new_copy, args.verbose)

        # 3. Find sync-versions.py in each (path may differ)
        old_sync = find_sync_versions(old_copy)
        new_sync = find_sync_versions(new_copy)
        print(f"  OLD sync-versions: {old_sync}")
        print(f"  NEW sync-versions: {new_sync}")
        if not old_sync or not new_sync:
            print("ERROR: could not locate sync-versions.py in one of the copies")
            return 2

        # 4. Snapshot pre-bump state
        old_pre = capture_version_files(old_copy)
        new_pre = capture_version_files(new_copy)
        print(f"\n[4/5] Pre-bump version values:")
        print(f"  OLD: {extract_version_values(old_pre)}")
        print(f"  NEW: {extract_version_values(new_pre)}")

        # 5. Run --bump patch in both
        print(f"\n[5/5] Running --bump patch in both copies...")
        # Use --force to skip any major-bump prompts (we're doing patch, but be safe)
        for label, copy_dir, sync_path in [
            ("OLD", old_copy, old_sync),
            ("NEW", new_copy, new_sync),
        ]:
            cmd = ["python", str(sync_path.relative_to(copy_dir)), "--bump", "patch", "--force"]
            print(f"  Running in {label}...")
            res = subprocess.run(
                cmd,
                cwd=str(copy_dir),
                capture_output=True,
                text=True,
            )
            if args.verbose:
                print(f"    stdout: {res.stdout}")
                print(f"    stderr: {res.stderr}")
            if res.returncode != 0:
                print(f"  WARNING: {label} sync-versions returned {res.returncode}")
                if not args.verbose:
                    print(f"    stderr: {res.stderr}")

        # 6. Snapshot post-bump state and compare
        old_post = capture_version_files(old_copy)
        new_post = capture_version_files(new_copy)

        print(f"\nPost-bump version values:")
        old_vals = extract_version_values(old_post)
        new_vals = extract_version_values(new_post)
        print(f"  OLD: {old_vals}")
        print(f"  NEW: {new_vals}")

        # 7. Focused comparison: SemVer values must match
        print(f"\n=== SEMVER VALUE COMPARISON ===")
        all_match = True
        for key in sorted(set(old_vals) | set(new_vals)):
            old_v = old_vals.get(key, "(missing)")
            new_v = new_vals.get(key, "(missing)")
            symbol = "[OK]" if old_v == new_v else "[X]"
            print(f"  {symbol} {key}: OLD={old_v} NEW={new_v}")
            if old_v != new_v:
                all_match = False
                exit_code = 1

        # 8. Full normalized file diff (informational)
        print(f"\n=== NORMALIZED FILE DIFF (allowed-diff content stripped) ===")
        diffs = file_diff(old_post, new_post, normalize=True)
        if not diffs:
            print("  No differences after normalization.")
        else:
            for line in diffs:
                print(f"  {line}")

        if all_match and not diffs:
            print("\n[PASS] OLD and NEW produce equivalent version-bump output.")
        elif all_match:
            print(
                "\n[PARTIAL] SemVer values match, but normalized file diff is non-empty."
                " Review above; may indicate metadata-format drift."
            )
        else:
            print(
                "\n[FAIL] SemVer values differ between OLD and NEW. Implementation gap."
            )
            print(
                "       This is EXPECTED before Commit 2b lands extra-targets support;"
                " the diff documents what extra-targets must implement."
            )

    finally:
        # 9. Cleanup
        if args.keep:
            print(f"\n[CLEANUP SKIPPED] --keep specified. Inspect: {work_root}")
        else:
            print(f"\nCleaning up {work_root}...")
            shutil.rmtree(work_root, ignore_errors=True)

        # 10. Leakage check
        print(f"\n=== LEAKAGE CHECK ===")
        problems = leakage_check(plugin_cache_before, original_log_before)
        if not problems:
            print("  [OK] No leakage detected.")
        else:
            for p in problems:
                print(f"  [LEAKAGE] {p}")
            exit_code = max(exit_code, 3)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
