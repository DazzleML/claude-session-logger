#!/bin/bash
#
# Common path definitions for scripts-repo
# Source this file in other scripts for consistent path handling
#
# Usage:
#   source "$(dirname "$0")/paths.sh"
#   # or
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/paths.sh"
#
# Note: Git hooks (pre-commit, etc.) are copied to .git/hooks/ and cannot
# source this file. They must use their own path detection via REPO_ROOT.
#

# Detect script location and derive paths
if [ -n "${BASH_SOURCE[0]}" ]; then
    SCRIPTS_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SCRIPTS_REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
fi

# Repository root (parent of scripts-repo)
REPO_ROOT="$(dirname "$SCRIPTS_REPO_DIR")"

# Scripts-repo subdirectories
GIT_HOOKS_DIR="$SCRIPTS_REPO_DIR/hooks"

# Key scripts
UPDATE_VERSION_SCRIPT="$SCRIPTS_REPO_DIR/update-version.sh"
INSTALL_HOOKS_SCRIPT="$SCRIPTS_REPO_DIR/install-hooks.sh"
AUDIT_SCRIPT="$SCRIPTS_REPO_DIR/audit_codebase.py"

# Plugin directories (at repo root)
PLUGIN_HOOKS_DIR="$REPO_ROOT/hooks"
PLUGIN_COMMANDS_DIR="$REPO_ROOT/commands"
PLUGIN_SCRIPTS_DIR="$REPO_ROOT/hooks/scripts"

# Version file
VERSION_FILE="$REPO_ROOT/version.py"

# Export for subprocesses
export REPO_ROOT
export SCRIPTS_REPO_DIR
export GIT_HOOKS_DIR
export UPDATE_VERSION_SCRIPT
export VERSION_FILE
