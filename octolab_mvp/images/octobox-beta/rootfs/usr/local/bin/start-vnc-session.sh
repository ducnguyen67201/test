#!/usr/bin/env bash
set -euo pipefail

# Manual validation:
#   docker build -t octobox-beta:vnc images/octobox-beta
#   docker run --rm -it -p 5900:5900 octobox-beta:vnc
#   docker run --rm -it -e VNC_LOCALHOST=0 -p 5900:5900 octobox-beta:vnc
#   docker exec -it <container> ss -ltnp | grep 5900

log() {
  echo "[start-vnc] $*"
}

export USER=pentester
export HOME=/home/pentester
export VNC_PORT=5900

# =============================================================================
# EVIDENCE/TLOG DIRECTORY SETUP
# Create /evidence/tlog/<LAB_ID>/ for command logging before session starts.
# This ensures the cmdlog hook has a writable target from the first command.
# SECURITY: Only accept safe identifiers (UUID or [A-Za-z0-9_-]+)
# =============================================================================
LAB_ID="${LAB_ID:-}"
if [[ -n "$LAB_ID" && "$LAB_ID" =~ ^[A-Za-z0-9_-]+$ ]]; then
    TLOG_DIR="/evidence/tlog/${LAB_ID}"
    if [[ ! -d "$TLOG_DIR" ]]; then
        log "Creating tlog directory: $TLOG_DIR"
        # Use install for atomic directory creation with correct ownership/perms
        install -d -m 0700 -o pentester -g pentester "$TLOG_DIR"
    fi
    # Debug output only when OCTOLAB_CMDLOG_DEBUG is set
    if [[ "${OCTOLAB_CMDLOG_DEBUG:-0}" == "1" ]]; then
        log "DEBUG: TLOG_DIR=$TLOG_DIR created (LAB_ID=$LAB_ID)"
    fi
elif [[ -n "$LAB_ID" ]]; then
    log "WARNING: LAB_ID contains invalid characters, skipping tlog dir creation"
fi
# =============================================================================

VNC_DISPLAY="${VNC_DISPLAY:-:0}"
VNC_RFBPORT="${VNC_RFBPORT:-5900}"
VNC_GEOMETRY="${VNC_GEOMETRY:-1280x800}"
VNC_DEPTH="${VNC_DEPTH:-24}"
VNC_LOCALHOST="${VNC_LOCALHOST:-1}"

DISPLAY="$VNC_DISPLAY"
export DISPLAY

log "Using DISPLAY=${DISPLAY} RFBPORT=${VNC_RFBPORT} LOCALHOST=${VNC_LOCALHOST} GEOMETRY=${VNC_GEOMETRY} DEPTH=${VNC_DEPTH}"

log "Preparing X/ICE socket directories"
for sock_dir in /tmp/.X11-unix /tmp/.ICE-unix; do
  if [[ ! -d "${sock_dir}" ]]; then
    mkdir -p "${sock_dir}"
    log "Created ${sock_dir}"
  fi
  chown root:root "${sock_dir}"
  chmod 1777 "${sock_dir}"
done

log "Preparing VNC directory at $HOME/.vnc"
sudo -u pentester mkdir -p "$HOME/.vnc"
chown pentester:pentester "$HOME/.vnc"
chmod 700 "$HOME/.vnc"

log "Selecting VNC password helper"
if command -v vncpasswd >/dev/null 2>&1; then
  PASSWORD_TOOL="$(command -v vncpasswd)"
elif command -v tigervncpasswd >/dev/null 2>&1; then
  PASSWORD_TOOL="$(command -v tigervncpasswd)"
else
  echo "[start-vnc] ERROR: No vncpasswd or tigervncpasswd found on PATH" >&2
  exit 1
fi

log "Generating VNC password file"
# Use VNC_PASSWORD from environment, or fallback to default only if explicitly allowed
VNC_PASSWORD="${VNC_PASSWORD:-}"
if [[ -z "$VNC_PASSWORD" ]]; then
    if [[ "${VNC_PASSWORD_ALLOW_DEFAULT:-0}" == "1" ]]; then
        log "WARNING: VNC_PASSWORD not set, using default (DEV ONLY)"
        VNC_PASSWORD="octo123"
    else
        log "ERROR: VNC_PASSWORD environment variable is required" >&2
        log "Set VNC_PASSWORD or VNC_PASSWORD_ALLOW_DEFAULT=1 for dev/testing" >&2
        exit 1
    fi
fi

sudo -u pentester /bin/bash -c "set -euo pipefail; echo '$VNC_PASSWORD' | '$PASSWORD_TOOL' -f > '$HOME/.vnc/passwd'"
chown pentester:pentester "$HOME/.vnc/passwd"
chmod 600 "$HOME/.vnc/passwd"

VNC_ARGS=("$DISPLAY" "-geometry" "$VNC_GEOMETRY" "-depth" "$VNC_DEPTH" "-rfbauth" "$HOME/.vnc/passwd" "-rfbport" "$VNC_RFBPORT")
if [[ "${VNC_LOCALHOST}" == "1" ]]; then
  VNC_ARGS+=("-localhost")
  log "Binding VNC to localhost only (set VNC_LOCALHOST=0 for dev access)"
else
  log "WARNING: VNC_LOCALHOST=${VNC_LOCALHOST} exposes VNC beyond localhost (dev-only)"
fi

log "Starting Xtigervnc"
sudo -u pentester Xtigervnc "${VNC_ARGS[@]}" &
VNC_PID=$!

log "Waiting for Xtigervnc to initialise"
sleep 2

log "Launching XFCE session for pentester"
sudo -u pentester DISPLAY=$DISPLAY dbus-launch --exit-with-session startxfce4 &

log "Blocking on Xtigervnc process ${VNC_PID}"
wait "$VNC_PID"