#!/usr/bin/env bash
# Hazel uninstaller
#
# Usage:
#   curl -LsSf https://raw.githubusercontent.com/ThomasPinella/hazel/main/scripts/uninstall.sh | sh
#
# What this does:
#   1. Stops and removes the dashboard systemd service (if installed)
#   2. Uninstalls hazel-ai via uv
#   3. Optionally removes ~/.hazel/ (config, workspace, sessions, memory)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}==>${NC} $*"; }
warn()  { echo -e "${YELLOW}==>${NC} $*"; }
error() { echo -e "${RED}ERROR:${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Step 1: Stop and remove the dashboard service
# ---------------------------------------------------------------------------
remove_dashboard_service() {
    local service="hazel-dashboard"

    if ! command -v systemctl &>/dev/null; then
        return
    fi

    if systemctl --user is-enabled "$service" &>/dev/null 2>&1; then
        info "Stopping and removing $service systemd service..."
        systemctl --user stop "$service" 2>/dev/null || true
        systemctl --user disable "$service" 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/${service}.service"
        systemctl --user daemon-reload 2>/dev/null || true
        info "Dashboard service removed"
    fi
}

# ---------------------------------------------------------------------------
# Step 2: Uninstall the Python package
# ---------------------------------------------------------------------------
uninstall_package() {
    export PATH="$HOME/.local/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        warn "uv not found — checking if hazel is installed another way..."
        if command -v pip &>/dev/null && pip show hazel-ai &>/dev/null 2>&1; then
            info "Uninstalling hazel-ai via pip..."
            pip uninstall hazel-ai -y
        else
            warn "hazel-ai does not appear to be installed"
        fi
        return
    fi

    if uv tool list 2>/dev/null | grep -q "hazel-ai"; then
        info "Uninstalling hazel-ai..."
        uv tool uninstall hazel-ai
        info "hazel-ai uninstalled"
    else
        warn "hazel-ai is not installed via uv tool"
    fi
}

# ---------------------------------------------------------------------------
# Step 3: Optionally remove user data
# ---------------------------------------------------------------------------
remove_user_data() {
    local hazel_dir="$HOME/.hazel"

    if [[ ! -d "$hazel_dir" ]]; then
        return
    fi

    echo ""
    warn "Found Hazel data directory: $hazel_dir"
    echo "  This contains your config, workspace, sessions, and memory."
    echo ""

    # If running non-interactively (piped), don't delete data
    if [[ ! -t 0 ]]; then
        warn "Running non-interactively — keeping $hazel_dir"
        warn "To remove it manually: rm -rf $hazel_dir"
        return
    fi

    read -rp "  Delete $hazel_dir? This cannot be undone. [y/N] " answer
    case "$answer" in
        [yY]|[yY][eE][sS])
            rm -rf "$hazel_dir"
            info "Removed $hazel_dir"
            ;;
        *)
            info "Keeping $hazel_dir"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo ""
    echo "  Hazel Uninstaller"
    echo ""

    remove_dashboard_service
    uninstall_package
    remove_user_data

    echo ""
    info "Hazel has been uninstalled."
    echo ""
}

main "$@"
