#!/bin/bash
#
# Run microvm-netd manually (for WSL or systems without systemd)
#
# Usage:
#   sudo ./run_netd.sh              # Run in foreground
#   sudo ./run_netd.sh --debug      # Run with debug output
#   sudo ./run_netd.sh --daemon     # Run in background (recommended for WSL)
#
# The daemon writes logs to /run/octolab/microvm-netd.log
#
# SECURITY:
# - Must run as root (creates bridges/TAPs via ip commands)
# - Socket accessible by octolab group only
# - No secrets logged

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETD_SCRIPT="$SCRIPT_DIR/microvm_netd.py"
SOCKET_DIR="/run/octolab"
SOCKET_PATH="${SOCKET_DIR}/microvm-netd.sock"
LOG_FILE="${SOCKET_DIR}/microvm-netd.log"
PID_FILE="${SOCKET_DIR}/microvm-netd.pid"
OCTOLAB_GROUP="octolab"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

# Check root
if [[ "$(id -u)" -ne 0 ]]; then
    log_error "microvm-netd must run as root"
    echo "Usage: sudo $0 [--debug] [--daemon]"
    exit 1
fi

# Check script exists
if [[ ! -f "$NETD_SCRIPT" ]]; then
    log_error "Cannot find netd script: $NETD_SCRIPT"
    exit 1
fi

# Check Python 3
if ! command -v python3 &>/dev/null; then
    log_error "python3 not found"
    exit 1
fi

# Parse arguments
daemon_mode=false
debug_mode=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --daemon|-d)
            daemon_mode=true
            shift
            ;;
        --debug)
            debug_mode=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Usage: sudo $0 [--debug] [--daemon]"
            exit 1
            ;;
    esac
done

# Create octolab group if needed
if ! getent group "$OCTOLAB_GROUP" &>/dev/null; then
    log_info "Creating $OCTOLAB_GROUP group..."
    groupadd -f "$OCTOLAB_GROUP"
fi

# Create and set up socket directory
mkdir -p "$SOCKET_DIR"
chown root:"$OCTOLAB_GROUP" "$SOCKET_DIR"
chmod 750 "$SOCKET_DIR"

# Remove stale socket if exists
if [[ -e "$SOCKET_PATH" ]]; then
    if [[ -S "$SOCKET_PATH" ]]; then
        log_info "Removing stale socket..."
        rm -f "$SOCKET_PATH"
    fi
fi

# Remove stale PID file if process is dead
if [[ -f "$PID_FILE" ]]; then
    old_pid=$(cat "$PID_FILE")
    if ! kill -0 "$old_pid" 2>/dev/null; then
        log_info "Removing stale PID file..."
        rm -f "$PID_FILE"
    else
        log_error "netd already running (PID $old_pid)"
        echo "  Stop with: sudo kill $old_pid"
        exit 1
    fi
fi

if [[ "$daemon_mode" == "true" ]]; then
    # Daemon mode
    log_info "Starting microvm-netd in background..."

    # Start daemon
    if [[ "$debug_mode" == "true" ]]; then
        nohup python3 "$NETD_SCRIPT" --debug >> "$LOG_FILE" 2>&1 &
    else
        nohup python3 "$NETD_SCRIPT" >> "$LOG_FILE" 2>&1 &
    fi
    pid=$!
    echo "$pid" > "$PID_FILE"

    # Wait for socket to appear
    max_wait=10
    waited=0
    while [[ $waited -lt $max_wait ]]; do
        if [[ -S "$SOCKET_PATH" ]]; then
            log_info "netd started (PID $pid)"
            echo "  Socket: $SOCKET_PATH"
            echo "  Logs:   tail -f $LOG_FILE"
            echo "  Stop:   sudo kill $pid"
            exit 0
        fi
        sleep 0.5
        waited=$((waited + 1))
    done

    log_error "netd failed to start"
    echo "  Check logs: tail -50 $LOG_FILE"

    # Clean up
    kill "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
else
    # Foreground mode
    log_info "Starting microvm-netd..."
    echo "  Socket: $SOCKET_PATH"
    echo "  Press Ctrl+C to stop"
    echo ""

    if [[ "$debug_mode" == "true" ]]; then
        exec python3 "$NETD_SCRIPT" --debug
    else
        exec python3 "$NETD_SCRIPT"
    fi
fi
