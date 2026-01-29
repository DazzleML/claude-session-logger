#!/bin/bash
#
# Manual version update script for preserve
# Updates version string without requiring a commit
# Useful for testing and manual version synchronization
#
# Usage:
#   ./scripts/update-version.sh [--auto]
#
# Options:
#   --auto    Run in automatic mode (for git hooks)
#

set -e

# Parse arguments
AUTO_MODE=false
BUILD_MODE=false
COMMIT_MODE=false
EXPLICIT_DATE=""
for arg in "$@"; do
    case $arg in
        --auto)
            AUTO_MODE=true
            ;;
        --build)
            BUILD_MODE=true
            ;;
        --commit)
            COMMIT_MODE=true
            ;;
        --date)
            shift
            EXPLICIT_DATE="$1"
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --auto       Run in automatic mode (for git hooks)"
            echo "  --build      Use today's date (for creating builds/releases)"
            echo "  --commit     Use last commit date (for version fixes)"
            echo "  --date DATE  Use explicit date (YYYYMMDD format)"
            echo ""
            echo "Default behavior:"
            echo "  - If working directory has changes: uses today's date"
            echo "  - If working directory is clean: uses last commit date"
            exit 0
            ;;
        *)
            ;;
    esac
done

# Colors for output (only in interactive mode)
if [ "$AUTO_MODE" = false ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color

    echo -e "${BLUE}claude-session-logger Version Updater${NC}"
    echo "======================================"
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

# Configuration
SOURCE_FILE="claude/version.py"

# Check if we're in the right directory
if [ ! -f "$SOURCE_FILE" ]; then
    # Try from scripts directory
    if [ -f "../$SOURCE_FILE" ]; then
        cd ..
    elif [ -f "../preserve/version.py" ]; then
        cd ..
        SOURCE_FILE="claude/version.py"
    else
        echo -e "${RED}Error:${NC} $SOURCE_FILE not found"
        echo "Please run from the project root directory"
        exit 1
    fi
fi

[ "$AUTO_MODE" = false ] && echo -e "${GREEN}[Version]${NC} Updating version in $SOURCE_FILE"

# Extract base version components separately
MAJOR=$(grep -E "^MAJOR = [0-9]+$" "$SOURCE_FILE" | sed 's/.*= //')
MINOR=$(grep -E "^MINOR = [0-9]+$" "$SOURCE_FILE" | sed 's/.*= //')
PATCH=$(grep -E "^PATCH = [0-9]+$" "$SOURCE_FILE" | sed 's/.*= //')

# Validate extraction
if [ -z "$MAJOR" ] || [ -z "$MINOR" ] || [ -z "$PATCH" ]; then
    echo -e "${RED}Error:${NC} Could not extract version components from $SOURCE_FILE"
    echo "Expected format: MAJOR = 0, MINOR = 1, PATCH = 0"
    exit 1
fi

# Extract phase if present
PHASE=$(grep -E "^PHASE = " "$SOURCE_FILE" | sed 's/.*= //' | sed 's/["'\'']//g' | sed 's/#.*//' | tr -d ' ')
if [ "$PHASE" = "None" ]; then
    PHASE=""
fi

# Construct base version
BASE_VERSION="${MAJOR}.${MINOR}.${PATCH}"
if [ -n "$PHASE" ]; then
    BASE_VERSION="${BASE_VERSION}-${PHASE}"
fi

[ "$AUTO_MODE" = false ] && echo "Base version: $BASE_VERSION"

# Get current version info
CURRENT_VERSION=$(grep -o '__version__ = ".*"' "$SOURCE_FILE" | cut -d'"' -f2)

# Get git information
if command -v git >/dev/null 2>&1 && [ -d ".git" -o -d "../.git" ]; then
    # Get branch name with fallback
    BRANCH_NAME=$(git branch --show-current 2>/dev/null || echo "unknown")
    # Replace any slashes in branch name with hyphens
    BRANCH_NAME=$(echo "$BRANCH_NAME" | tr '/' '-')

    # Get build information
    if [ "$AUTO_MODE" = true ]; then
        # In auto mode, we're about to create a new commit, so add 1
        BUILD_NUMBER=$(($(git rev-list --count HEAD 2>/dev/null || echo "0") + 1))
    else
        # In manual mode, use the actual count
        BUILD_NUMBER=$(git rev-list --count HEAD 2>/dev/null || echo "0")
    fi

    # Get date and hash
    if git rev-parse HEAD >/dev/null 2>&1; then
        # We have at least one commit
        COMMIT_HASH=$(git rev-parse --short=8 HEAD)

        # Determine date based on mode and options
        if [ -n "$EXPLICIT_DATE" ]; then
            # Explicit date provided
            COMMIT_DATE="$EXPLICIT_DATE"
            [ "$AUTO_MODE" = false ] && echo "Using explicit date: $COMMIT_DATE"
        elif [ "$AUTO_MODE" = true ]; then
            # In auto mode (pre-commit), use TODAY's date since we're making the commit NOW
            COMMIT_DATE=$(date +%Y%m%d)
        elif [ "$BUILD_MODE" = true ]; then
            # Explicit build mode - use today's date
            COMMIT_DATE=$(date +%Y%m%d)
            echo "Using today's date for build: $COMMIT_DATE"
        elif [ "$COMMIT_MODE" = true ]; then
            # Explicit commit mode - use HEAD's date
            COMMIT_DATE=$(git log -1 --format=%cd --date=format:%Y%m%d HEAD)
            echo "Using last commit date: $COMMIT_DATE"
        else
            # Smart default based on working directory state
            # Check what files are modified
            MODIFIED_FILES=$(git status --porcelain 2>/dev/null)

            # Check if ONLY version.py is modified
            VERSION_ONLY_MODIFIED=false
            if [ -n "$MODIFIED_FILES" ]; then
                # Remove version.py entries from the list
                OTHER_CHANGES=$(echo "$MODIFIED_FILES" | grep -v "version.py" || true)

                if [ -z "$OTHER_CHANGES" ]; then
                    # Only version.py is modified
                    VERSION_ONLY_MODIFIED=true
                fi
            fi

            if [ "$VERSION_ONLY_MODIFIED" = true ]; then
                # Only version.py changed - treat as clean for date purposes
                COMMIT_DATE=$(git log -1 --format=%cd --date=format:%Y%m%d HEAD)
                echo -e "${GREEN}Note:${NC} Only version.py modified - using last commit date: $COMMIT_DATE"
            elif [ -n "$MODIFIED_FILES" ]; then
                # Other files changed - likely creating a build
                COMMIT_DATE=$(date +%Y%m%d)
                echo -e "${YELLOW}Note:${NC} Working directory has uncommitted changes - using today's date: $COMMIT_DATE"
            else
                # Clean working directory - use HEAD date
                COMMIT_DATE=$(git log -1 --format=%cd --date=format:%Y%m%d HEAD)
                echo -e "${GREEN}Note:${NC} Working directory clean - using last commit date: $COMMIT_DATE"
            fi
        fi
    else
        # No commits yet (initial commit)
        COMMIT_DATE=$(date +%Y%m%d)
        COMMIT_HASH="initial0"
    fi
else
    # No git available
    BRANCH_NAME="unknown"
    BUILD_NUMBER="0"
    COMMIT_DATE=$(date +%Y%m%d)
    COMMIT_HASH="nogit000"
fi

# Generate new version string
NEW_VERSION="${BASE_VERSION}_${BRANCH_NAME}_${BUILD_NUMBER}-${COMMIT_DATE}-${COMMIT_HASH}"

# Check if update is needed
if [ "$CURRENT_VERSION" = "$NEW_VERSION" ]; then
    [ "$AUTO_MODE" = false ] && echo -e "${YELLOW}Version already up to date: $NEW_VERSION${NC}"
    exit 0
fi

# Update the file
[ "$AUTO_MODE" = false ] && echo -e "${GREEN}Updating from:${NC} $CURRENT_VERSION"
[ "$AUTO_MODE" = false ] && echo -e "${GREEN}Updating to:${NC}   $NEW_VERSION"

# Create backup
cp "$SOURCE_FILE" "${SOURCE_FILE}.backup"

# Update version string
if sed "s/__version__ = \".*\"/__version__ = \"$NEW_VERSION\"/" "$SOURCE_FILE" > "${SOURCE_FILE}.tmp"; then
    mv "${SOURCE_FILE}.tmp" "$SOURCE_FILE"
    rm -f "${SOURCE_FILE}.backup"

    if [ "$AUTO_MODE" = true ]; then
        # In auto mode (git hook), stage the file
        git add "$SOURCE_FILE" 2>/dev/null || true
    fi

    [ "$AUTO_MODE" = false ] && echo -e "${GREEN}✅ Version updated successfully!${NC}"
else
    mv "${SOURCE_FILE}.backup" "$SOURCE_FILE"
    echo -e "${RED}Error: Failed to update version${NC}"
    exit 1
fi

# Verify the update
UPDATED_VERSION=$(grep -o '__version__ = ".*"' "$SOURCE_FILE" | cut -d'"' -f2)
if [ "$UPDATED_VERSION" != "$NEW_VERSION" ]; then
    echo -e "${RED}Error: Version update verification failed${NC}"
    echo "Expected: $NEW_VERSION"
    echo "Got: $UPDATED_VERSION"
    exit 1
fi

[ "$AUTO_MODE" = false ] && echo ""
[ "$AUTO_MODE" = false ] && echo "Version string format:"
[ "$AUTO_MODE" = false ] && echo "  VERSION_BRANCH_BUILD-YYYYMMDD-COMMITHASH"
[ "$AUTO_MODE" = false ] && echo "  $NEW_VERSION"