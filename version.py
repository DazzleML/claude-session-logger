"""
Version information for claude-session-logger.

This file is automatically updated by git pre-commit hooks.
Format: VERSION_BRANCH_BUILD-YYYYMMDD-COMMITHASH

Example: 0.1.0_main_5-20260129-a1b2c3d4

Components:
- VERSION: Semantic version (MAJOR.MINOR.PATCH)
- BRANCH: Git branch name
- BUILD: Commit count
- YYYYMMDD: Commit date
- COMMITHASH: Short commit hash
"""

# Semantic version components
MAJOR = 0
MINOR = 1
PATCH = 5

# Optional release phase (alpha, beta, rc1, rc2, etc.)
# Set to None for stable releases
PHASE = None  # Stable release

# Full version string - updated by git pre-commit hook
# DO NOT EDIT THIS LINE MANUALLY
# Note: Hash reflects the commit this version builds upon (HEAD at commit time)
# The hash will be one commit behind after the commit is created (git limitation)
__version__ = "0.1.5_main_12-20260201-d2c4aa04"


def get_version():
    """Return the full version string including branch and build info."""
    return __version__


def get_base_version():
    """Return the semantic version string (MAJOR.MINOR.PATCH) with optional phase."""
    if "_" in __version__:
        base = __version__.split("_")[0]
    else:
        base = f"{MAJOR}.{MINOR}.{PATCH}"

    if PHASE:
        base = f"{base}-{PHASE}"

    return base


def get_version_dict():
    """Return version information as a dictionary."""
    parts = __version__.split("_")
    if len(parts) >= 3:
        base_version = parts[0]
        branch = parts[1]
        build_info = "_".join(parts[2:])
        build_parts = build_info.split("-")

        return {
            "full": __version__,
            "base": base_version,
            "branch": branch,
            "build": build_parts[0] if len(build_parts) > 0 else "",
            "date": build_parts[1] if len(build_parts) > 1 else "",
            "commit": build_parts[2] if len(build_parts) > 2 else "",
        }

    return {
        "full": __version__,
        "base": get_base_version(),
        "branch": "unknown",
        "build": "0",
        "date": "",
        "commit": "",
    }


# For convenience in imports
VERSION = get_version()
BASE_VERSION = get_base_version()
