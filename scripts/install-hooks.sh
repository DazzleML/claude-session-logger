#!/bin/bash
#
# Install git hooks for preserve project
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}claude-session-logger Git Hook Installer${NC}"
echo "======================================="
echo ""

# Find git directory
if [ -d ".git" ]; then
    GIT_DIR=".git"
elif [ -d "../.git" ]; then
    GIT_DIR="../.git"
else
    echo -e "${RED}Error:${NC} Git repository not found"
    echo "Please run from the project root directory"
    exit 1
fi

HOOKS_DIR="$GIT_DIR/hooks"
SCRIPT_DIR="$(dirname "$0")"

echo -e "${GREEN}Found git repository at:${NC} $GIT_DIR"
echo ""

# Check if hooks already exist
if [ -f "$HOOKS_DIR/pre-commit" ]; then
    echo -e "${YELLOW}Warning:${NC} pre-commit hook already exists"
    echo "Do you want to overwrite it? (y/n)"
    read -r response
    if [ "$response" != "y" ] && [ "$response" != "Y" ]; then
        echo "Installation cancelled"
        exit 0
    fi
fi

# Install pre-commit hook
echo -e "${GREEN}Installing pre-commit hook...${NC}"
cp "$SCRIPT_DIR/hooks/pre-commit" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"

# Make version update script executable
if [ -f "$SCRIPT_DIR/update-version.sh" ]; then
    chmod +x "$SCRIPT_DIR/update-version.sh"
    echo -e "${GREEN}Made update-version.sh executable${NC}"
fi

echo ""
echo -e "${GREEN}✅ Git hooks installed successfully!${NC}"
echo ""
echo "The pre-commit hook will:"
echo "  • Automatically update version.py with build information"
echo "  • Prevent committing private files to public branches"
echo "  • Check for oversized files (>10MB)"
echo ""
echo "You can manually update the version at any time with:"
echo "  ./scripts/update-version.sh"
echo ""
echo -e "${BLUE}Version format:${NC}"
echo "  VERSION_BRANCH_BUILD-YYYYMMDD-COMMITHASH"
echo "  Example: 0.4.0_main_42-20250920-a1b2c3d4"