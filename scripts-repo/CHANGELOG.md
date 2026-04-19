# Changelog

All notable changes to git-repokit-common are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note on versioning:** Early releases had a non-linear version sequence. v0.1.3-alpha and v0.1.4-alpha were cut *after* v0.2.1 as experimental side-branches before returning to the 0.2.x line at v0.2.2. Entries below are listed in commit order (newest first), not version order.

## [Unreleased]

## [0.2.4] - 2026-04-19

### Fixed

- **`gh_issue_full.py` null `commit_id` crash**: `process_timeline()` crashed with `TypeError: 'NoneType' object is not subscriptable` when a GitHub timeline event returned `commit_id=None` (explicit JSON null rather than missing key). Root cause: `dict.get(key, default)` only returns `default` when the key is missing, not when the value is `None`. Fixed the `"referenced"` event branch with idiomatic `(item.get("commit_id") or "")[:7]` null-and-empty coercion. The `"closed"` branch was already guarded correctly. Reproduced and verified against `DazzleTools/dazzlecmd#13`.

## [0.2.3] - 2026-04-07

### Added

- **Tag-only push detection in `pre-push` hook**: Tag pushes don't change code, so running the full pytest suite and syntax checks is wasted time. The hook now reads stdin ref info from git and exits early when every ref being pushed is a tag (`refs/tags/*`), printing `Tag-only push -- skipping validation`.

## [0.2.2] - 2026-04-04

### Added

- **`update-common.sh`**: subtree management script for consuming projects. Supports `pull` (default), `--check` (version status vs upstream), and `--push` (propagate local changes upstream).
- **`VERSION` file** (`0.2.2`): simple top-level version tracking. `update-common.sh --check` uses it to compare local vs upstream at a glance.
- **`docs/sync-versions.md`**: reference documentation for the version management system -- configuration, PEP 440 mapping, git hooks integration, and full flag reference.

### Fixed

- **`demo/build_demo.py` and `demo/demo_render.py` path resolution**: after moving into `demo/` subdirectory (v0.1.4-alpha), the scripts' `Path(__file__).resolve().parent.parent` pattern resolved to `scripts/` instead of the project root. Updated to `parent.parent.parent` and fixed the default VHS tape path from `scripts/vhs/` to `scripts/demo/vhs/`.

### Removed

- **`.github/workflows/ci.yml` and `release.yml`**: template leftovers that always failed because this repo isn't a pip-installable package.
- **`tests/test_version.py`**: template placeholder with literal `$PACKAGE_NAME` that never worked here. Test infrastructure (`conftest.py`, `tests/one-offs/`, `tests/output/`) retained for future use.

### Refs

- Refs #1 (consumer tracking)

## [0.1.4-alpha] - 2026-04-04

### Added

- **`git_tag_exists()` helper in `sync-versions.py`**: checks whether a given git tag exists in the repository.

### Fixed

- **`--check` CHANGELOG validation on new repos**: new projects without their first release would fail `--check` because the CHANGELOG compare link references a tag that doesn't exist yet. Now accepts the `releases/tag/...` link format (used for first releases with no prior tag to compare against), and when the tag doesn't exist yet reports informational `[--]` instead of error `[X]` -- avoiding the need for `--force` on every new project.

### Changed

- **Demo tooling reorganized into `demo/` subdirectory**: `build_demo.py`, `demo_render.py`, and `vhs/` moved into `demo/` to reduce clutter. Most projects don't use demo recording; keeping it in a single subdirectory makes the top level cleaner.

### Removed

- **`pyproject.toml.comfyui` and `pyproject.toml.pypi`**: redundant archetype templates that belong in `git-repokit-template`, not in common scripts.

## [0.1.3-alpha] - 2026-04-03

### Added

- **`[tool.repokit-common]` section in `pyproject.toml`**: explicit config with `version-source`, `changelog`, `repo-url`, `tag-prefix`, `tag-format`, and `private-patterns`.
- **Git hooks (via repokit-common)**: `pre-commit` version sync + private file protection, `post-commit` hash refresh, `pre-push` syntax and test checks.
- **`tag-format` config option in `sync-versions.py`**: `"pep440"` (default) produces `v0.1.3a1` style tags for PyPI compatibility; `"human"` produces `v0.1.3-alpha` style tags for projects using human-readable tags that match CHANGELOG headers. Unknown values warn and fall back to `pep440`.
- **`scripts/README.md` tag-format documentation**: format table with guidance on when to use each option.

### Fixed

- **`sync-versions.py to_tag()` PEP 440 hardcoding**: `to_tag()` ignored the project's chosen `tag-format` and always emitted PEP 440 style tags. This caused `--check` to reject valid human-readable CHANGELOG links as mismatches, and `update_changelog_links()` to silently rewrite those links into broken PEP 440 URLs. The corruption cascaded to subsequent releases. Fixed by honoring `tag-format` in all tag-producing code paths.
- **`pre-push` hook package detection**: the auto-detection logic only checked root-level directories for `__init__.py`, missing `src/` layout projects. Now also walks `src/*/` when a root-level package isn't found.
- **`pre-push` hook syntax check**: used a `py_compile` glob that failed when no `.py` files existed at the target path. Replaced with `compileall -q`, which handles empty directories gracefully.
- **`pre-push` hook test runner**: treated "no tests collected" as a pytest failure, blocking pushes to `main` on projects without tests. Now skips the test step when no `test_*.py` files exist.
- **Dynamic version import in downstream consumers**: `locked.py --version` replaced a hardcoded version string with a dynamic import from `_version.py` (`get_base_version`).
- **Stale embedded version metadata**: `locked/.wtf.json` was stuck at `0.1.1`; updated to `0.1.3`.

### Changed

- **Version**: `0.1.2-alpha` -> `0.1.3-alpha`.
- **`_version.py __version__` now includes git metadata**: branch, build count, date, and commit hash are appended via `sync-versions.py`.

### Refs

- Refs #3 (epic -- shared tooling integration)

### Design

- `2026-04-02__23-00-06__dev-workflow_sync-versions-tag-format-and-check-robustness.md`

## [0.2.1] - 2026-03-31

### Changed

- **README and TODO updated to use the git subtree workflow** instead of git submodule. Replaced submodule instructions with `git subtree add --prefix=scripts`, added a named remote recipe (`git remote add repokit-common`), and documented the pull/push cycle for bidirectional sync. Also noted that pre-existing files in `scripts/` must be moved out first, since `git subtree add` requires an empty prefix directory.

## [0.2.0] - 2026-03-31

### Changed

- **Scripts moved to repo root for submodule compatibility** (later superseded by subtree approach in v0.2.1). When added as a submodule at `scripts/repokit-common/`, having scripts inside a nested `scripts/` subdirectory caused `scripts/repokit-common/scripts/sync-versions.py` -- double nesting. Moving everything to the repo root produces the cleaner `scripts/repokit-common/sync-versions.py`. `install-hooks.sh` uses `$(dirname "$0")` so paths resolve correctly regardless of where the submodule is checked out.
- **`FUNDING.yml` expanded to the full format**; paths in README and TODO adjusted accordingly.

## [0.1.0] - 2026-03-31

### Added

- **Initial DazzleTools shared toolbox**, parameterized for reuse across projects.
- **Git hooks** (`hooks/`):
  - `pre-commit`: version sync, private content protection, large file blocking
  - `post-commit`: version hash refresh
  - `pre-push`: syntax check, pytest, debug statement detection (auto-detects package directory via `__init__.py`)
- **Version management**:
  - `sync-versions.py`: reads config from `pyproject.toml [tool.repokit-common]`
  - `update-version.sh`: legacy bash updater (deprecated in favor of `sync-versions.py`)
- **GitHub tools**:
  - `gh_issue_full.py`: full issue context viewer (timeline, cross-refs, sub-issues, comments)
  - `gh_sub_issues.py`: sub-issue relationship management
- **Claude Code session tools**:
  - `search_sesslog.py`: search JSONL session transcripts
  - `extract_tool_result.py`: extract tool results from sessions
- **CLI demo recording**: `build_demo.py`, `demo_render.py` (template/example), `vhs/` tape templates.
- **Utilities**: `install-hooks.sh` (auto-detects project name), `paths.sh`, `safe_move.sh`.
- **`TODO.md`**: post-setup checklist for consuming projects.
- **`README.md`**: usage instructions and configuration docs.

All project-specific hardcoding (`wtf-restarted`, `comfydbg`) was replaced with auto-detection or `$placeholder` variables. Project-level files (`.github/`, `CONTRIBUTING.md`, `.repokit.json`, `.vscode/`) were substituted with real values for `git-repokit-common`.

[Unreleased]: https://github.com/DazzleTools/git-repokit-common/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/DazzleTools/git-repokit-common/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/DazzleTools/git-repokit-common/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/DazzleTools/git-repokit-common/compare/v0.1.4-alpha...v0.2.2
[0.1.4-alpha]: https://github.com/DazzleTools/git-repokit-common/compare/v0.1.3-alpha...v0.1.4-alpha
[0.1.3-alpha]: https://github.com/DazzleTools/git-repokit-common/compare/v0.2.1...v0.1.3-alpha
[0.2.1]: https://github.com/DazzleTools/git-repokit-common/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/DazzleTools/git-repokit-common/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/DazzleTools/git-repokit-common/releases/tag/v0.1.0
