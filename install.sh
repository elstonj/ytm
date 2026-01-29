#!/usr/bin/env bash
# ytm-cli installer
# Created by Jack Elston
#
# Usage: curl -sSL https://raw.githubusercontent.com/elstonj/ytm/main/install.sh | bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo ""
echo "ytm-cli installer"
echo "================="
echo ""

# Check for Python 3.10+
check_python() {
    if command -v python3 &> /dev/null; then
        version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            echo -e "${GREEN}✓${NC} Python $version found"
            return 0
        fi
    fi
    echo -e "${RED}✗${NC} Python 3.10+ is required"
    echo "  Install Python 3.10 or later and try again"
    exit 1
}

# Check for pip
check_pip() {
    if command -v pip3 &> /dev/null; then
        echo -e "${GREEN}✓${NC} pip3 found"
        return 0
    elif python3 -m pip --version &> /dev/null; then
        echo -e "${GREEN}✓${NC} pip found (via python3 -m pip)"
        return 0
    fi
    echo -e "${RED}✗${NC} pip is required"
    echo "  Install pip and try again"
    exit 1
}

# Check for mpv
check_mpv() {
    if command -v mpv &> /dev/null; then
        echo -e "${GREEN}✓${NC} mpv found"
        return 0
    fi
    echo -e "${YELLOW}!${NC} mpv not found (required for audio playback)"
    echo ""
    echo "  Install mpv:"
    echo "    Ubuntu/Debian: sudo apt install mpv"
    echo "    macOS:         brew install mpv"
    echo "    Fedora:        sudo dnf install mpv"
    echo "    Arch:          sudo pacman -S mpv"
    echo ""
    read -p "  Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
}

# Check for git
check_git() {
    if command -v git &> /dev/null; then
        echo -e "${GREEN}✓${NC} git found"
        return 0
    fi
    echo -e "${RED}✗${NC} git is required"
    echo "  Install git and try again"
    exit 1
}

echo "Checking dependencies..."
echo ""
check_python
check_pip
check_mpv
check_git

echo ""
echo "Installing ytm-cli..."
echo ""

# Create temp directory
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

# Clone and install
cd "$TMPDIR"
git clone --depth 1 https://github.com/elstonj/ytm.git
cd ytm

if command -v pip3 &> /dev/null; then
    pip3 install --user .
else
    python3 -m pip install --user .
fi

echo ""
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "Usage:"
echo "  ytm search \"song name\"   - Search and play"
echo "  ytm play \"song name\"     - Play first match"
echo "  ytm radio \"song name\"    - Play with similar songs"
echo "  ytm library              - Browse your library"
echo "  ytm auth                 - Authenticate with YouTube Music"
echo ""
echo "Note: You may need to add ~/.local/bin to your PATH:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
echo ""
