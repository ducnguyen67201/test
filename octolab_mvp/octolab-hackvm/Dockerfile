# Debian-based HackVM - Browser-accessible attack box via noVNC with script-based command logging
FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    USERNAME=pentester \
    USER=pentester \
    DISPLAY=:0 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080

# Desktop, VNC, noVNC, tools, tlog for structured session logging
# XFCE dependencies for stable desktop session on Debian 12-slim
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        # Core XFCE components
        xfce4 \
        xfce4-session \
        xfce4-panel \
        xfce4-settings \
        xfce4-terminal \
        xfce4-goodies \
        xfce4-notifyd \
        # VNC server and client
        tigervnc-standalone-server \
        tigervnc-tools \
        # noVNC web client
        novnc \
        websockify \
        # X11 and DBus essentials for desktop session
        dbus-x11 \
        x11-utils \
        x11-xserver-utils \
        xauth \
        xfonts-base \
        xfonts-75dpi \
        xfonts-100dpi \
        # PolicyKit for desktop integration
        policykit-1 \
        # Fallback window manager and terminal
        twm \
        xterm \
        # Tools for healthcheck and debugging
        procps \
        netcat-openbsd \
        # Pentesting and general tools
        nmap \
        curl \
        wget \
        iputils-ping \
        git \
        python3 \
        python3-pip \
        vim \
        nano \
        util-linux \
        # Structured session logging
        tlog && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Build-time sanity checks for XFCE components
RUN command -v startxfce4 && \
    command -v xfce4-session && \
    command -v dbus-launch && \
    command -v pgrep && \
    command -v nc && \
    echo "XFCE build checks passed"

# Non-root user
RUN useradd -m -s /bin/bash "${USERNAME}" && \
    echo "${USERNAME}:pentester123" | chpasswd && \
    usermod -aG sudo ${USERNAME} && \
    mkdir -p /home/${USERNAME}/.vnc && \
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}
# Note: terminalrc is created at runtime in xstartup because /home/pentester is mounted as a volume

# Create /evidence directory for command logging
RUN mkdir -p /evidence && \
    chmod 777 /evidence

# Install and configure script-based wrapper for command logging (legacy, kept for backwards compat)
# octolog-shell wraps /bin/bash with script to log all terminal I/O to /evidence/commands.log
# and timing data to /evidence/commands.time
COPY octolog-shell /usr/local/bin/octolog-shell
RUN chmod +x /usr/local/bin/octolog-shell && \
    echo "/usr/local/bin/octolog-shell" >> /etc/shells

# Keep pentester's shell as /bin/bash - tlog is invoked via wrapper, not login shell
# This prevents terminal from closing if tlog fails to start
# tlog config is generated at runtime in entrypoint.sh with lab-specific paths
# SECURITY: tlog is configured with log.input=false to avoid capturing passwords
RUN usermod -s /bin/bash ${USERNAME}

# Create octobox-shell wrapper: tlog with safe fallback to bash
# This wrapper is invoked by XFCE Terminal (via terminalrc), not as a login shell
# If tlog fails (missing config, unwritable evidence), terminal still opens with bash
RUN cat > /usr/local/bin/octobox-shell << 'OCTOBOX_SHELL_EOF'
#!/bin/bash
# OctoBox shell wrapper: tlog session recording with safe fallback
# NEVER exits without exec-ing a shell - terminal must stay open
# Logs to /tmp/octobox-shell.log (created by entrypoint.sh)

LOG=/tmp/octobox-shell.log
CONF=/etc/tlog/tlog-rec-session.conf

ts(){ date '+%Y-%m-%d %H:%M:%S'; }
log(){ echo "[$(ts)] $*" >> "$LOG" 2>/dev/null || true; }

# ============================================================================
# Resolve LAB_ID: env > file > unknown
# ============================================================================
LAB_ID="${OCTOLAB_LAB_ID:-}"
if [ -z "$LAB_ID" ] && [ -f /etc/octobox/lab_id ]; then
    LAB_ID="$(cat /etc/octobox/lab_id 2>/dev/null | tr -d '[:space:]')"
fi
LAB_ID="${LAB_ID:-unknown}"

EVID_DIR="/evidence/tlog/${LAB_ID}"

# ============================================================================
# Determine if we have a TTY
# ============================================================================
HAS_TTY=0
if [ -t 0 ]; then
    HAS_TTY=1
fi

# Always log start (even if non-interactive)
log "START lab=${LAB_ID} tty=${HAS_TTY} pid=$$"

# ============================================================================
# Non-interactive: skip tlog entirely
# ============================================================================
if [ "$HAS_TTY" = "0" ]; then
    exec /bin/bash "$@"
fi

# ============================================================================
# Check evidence directory is writable
# ============================================================================
mkdir -p "$EVID_DIR" 2>/dev/null || true
if ! ( : > "$EVID_DIR/.write_test" ) 2>/dev/null; then
    log "WARN lab=${LAB_ID} evidence not writable; fallback=bash"
    rm -f "$EVID_DIR/.write_test" 2>/dev/null || true
    exec /bin/bash -i
fi
rm -f "$EVID_DIR/.write_test" 2>/dev/null || true

# ============================================================================
# Check tlog config exists
# ============================================================================
if [ ! -f "$CONF" ]; then
    log "WARN lab=${LAB_ID} missing tlog config; fallback=bash"
    exec /bin/bash -i
fi

# ============================================================================
# Preflight: quick tlog sanity check
# ============================================================================
# Run tlog with a no-op command to verify it can start
# Timeout after 2 seconds to avoid hangs
if ! timeout 2 /usr/bin/tlog-rec-session -c 'exit 0' >/dev/null 2>&1; then
    log "WARN lab=${LAB_ID} tlog preflight failed; fallback=bash"
    exec /bin/bash -i
fi

# ============================================================================
# Launch tlog-rec-session
# ============================================================================
# Config has log.input=false (SECURITY: never capture typed input)
log "OK lab=${LAB_ID} launching tlog-rec-session"
exec /usr/bin/tlog-rec-session
OCTOBOX_SHELL_EOF

RUN chmod 0755 /usr/local/bin/octobox-shell && \
    echo "/usr/local/bin/octobox-shell" >> /etc/shells

# Legacy: script_wrapper.sh, octobox_logging.sh, and tlog experiments are kept for reference
# They have been replaced by octobox-shell wrapper with tlog (evidence v3.0)

# Entrypoint script (runs as root to fix permissions, then switches to user)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Keep running as root for entrypoint; it will switch to ${USERNAME} user
WORKDIR /home/${USERNAME}

# Startup script for VNC + noVNC
COPY --chown=${USERNAME}:${USERNAME} startup.sh /home/${USERNAME}/startup.sh

# Bashrc logging script (PROMPT_COMMAND fallback)
COPY bashrc_logging.sh /etc/profile.d/octolog.sh
RUN chmod +x /etc/profile.d/octolog.sh

# Create robust XFCE session launcher (runs as pentester, called by xstartup)
# This is a long-running process that keeps VNC alive
RUN mkdir -p /etc/octobox /usr/local/bin && \
    cat > /usr/local/bin/octobox-xstartup << 'XFCE_LAUNCHER_EOF'
#!/bin/bash
# OctoBox XFCE session launcher for VNC
# This script MUST remain running for VNC session to stay alive
# Logs to ~/.vnc/xstartup.log for debugging

set -e

# Ensure HOME/USER are set before any paths are used
export HOME="${HOME:-/home/pentester}"
export USER="${USER:-pentester}"

# Ensure VNC dir exists (home may be a volume)
mkdir -p "$HOME/.vnc" 2>/dev/null || true

# Setup logging with fallback if home isn't writable
LOGFILE="$HOME/.vnc/xstartup.log"
if ! ( : >> "$LOGFILE" ) 2>/dev/null; then
    LOGFILE="/tmp/octobox-xstartup.log"
fi
exec >> "$LOGFILE" 2>&1

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== OctoBox XFCE session starting ==="
log "USER=$USER HOME=$HOME DISPLAY=$DISPLAY"
log "Logging to: $LOGFILE"

# ============================================================================
# Export OCTOLAB_LAB_ID from /etc/octobox/lab_id if not already set
# This ensures terminals launched from XFCE have access to LAB_ID
# ============================================================================
if [ -z "${OCTOLAB_LAB_ID:-}" ] && [ -f /etc/octobox/lab_id ]; then
    export OCTOLAB_LAB_ID="$(cat /etc/octobox/lab_id 2>/dev/null | tr -d '[:space:]')"
    log "Loaded OCTOLAB_LAB_ID from file: ${OCTOLAB_LAB_ID:-unknown}"
else
    log "OCTOLAB_LAB_ID from env: ${OCTOLAB_LAB_ID:-not set}"
fi

# Set remaining environment variables
export SHELL="${SHELL:-/bin/bash}"
export LANG="${LANG:-C.UTF-8}"
export DISPLAY="${DISPLAY:-:1}"

# Create XDG runtime directory (required by many desktop apps)
export XDG_RUNTIME_DIR="/tmp/xdg-${USER}"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
log "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"

# Create user directories if missing (volume mounts may not have them)
mkdir -p "$HOME/.cache" "$HOME/.config" "$HOME/.local/share"
chown -R "$USER:$USER" "$HOME/.cache" "$HOME/.config" "$HOME/.local/share" 2>/dev/null || true

# ============================================================================
# Force XFCE Terminal to use octobox-shell wrapper (override any stale config)
# HOME may be a volume with old configs, so we ALWAYS overwrite terminalrc
# ============================================================================
TERMINAL_DIR="$HOME/.config/xfce4/terminal"
mkdir -p "$TERMINAL_DIR" 2>/dev/null || true
cat > "$TERMINAL_DIR/terminalrc" << 'TERMRC_EOF'
[Configuration]
CommandLoginShell=FALSE
Command=/usr/local/bin/octobox-shell
MiscAlwaysShowTabs=FALSE
MiscMenubarDefault=TRUE
MiscShowUnsafePasteDialog=FALSE
ScrollingLines=10000
FontName=Monospace 11
TERMRC_EOF
chown -R "$USER:$USER" "$TERMINAL_DIR" 2>/dev/null || true
log "Wrote terminalrc: Command=/usr/local/bin/octobox-shell"

# Unset any inherited session manager (prevents conflicts)
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS

# Load X resources if available (non-fatal)
[ -f "$HOME/.Xresources" ] && xrdb "$HOME/.Xresources" 2>/dev/null || true

# Set root window background (visual feedback that X is running)
xsetroot -solid "#2d2d2d" 2>/dev/null || true

# Start DBus session bus (required for XFCE)
if command -v dbus-launch >/dev/null 2>&1; then
    log "Starting DBus session bus..."
    eval "$(dbus-launch --sh-syntax)"
    log "DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
    log "DBUS_SESSION_BUS_PID=$DBUS_SESSION_BUS_PID"
else
    log "WARNING: dbus-launch not found, XFCE may not work correctly"
fi

# Start XFCE session
log "Starting XFCE session via xfce4-session..."
if command -v xfce4-session >/dev/null 2>&1; then
    # xfce4-session is the main session manager; exec to replace this script
    exec xfce4-session
else
    # Fallback: try startxfce4 (wrapper script)
    log "xfce4-session not found, trying startxfce4..."
    if command -v startxfce4 >/dev/null 2>&1; then
        exec startxfce4
    else
        log "FATAL: Neither xfce4-session nor startxfce4 found!"
        exit 1
    fi
fi
XFCE_LAUNCHER_EOF

RUN chmod 0755 /usr/local/bin/octobox-xstartup

# Create debug script for troubleshooting terminal/tlog issues
RUN cat > /usr/local/bin/octobox-debug-terminal << 'DEBUG_EOF'
#!/bin/bash
# OctoBox Terminal Debug Script
# Run this to diagnose tlog/terminal issues (no secrets printed)

echo "=== OctoBox Terminal Debug ==="
echo "Date: $(date -Iseconds)"
echo

echo "=== LAB_ID Resolution ==="
echo "OCTOLAB_LAB_ID env: ${OCTOLAB_LAB_ID:-<not set>}"
if [ -f /etc/octobox/lab_id ]; then
    echo "/etc/octobox/lab_id: $(cat /etc/octobox/lab_id)"
else
    echo "/etc/octobox/lab_id: <file not found>"
fi

# Determine effective LAB_ID
LAB_ID="${OCTOLAB_LAB_ID:-}"
if [ -z "$LAB_ID" ] && [ -f /etc/octobox/lab_id ]; then
    LAB_ID="$(cat /etc/octobox/lab_id 2>/dev/null | tr -d '[:space:]')"
fi
LAB_ID="${LAB_ID:-unknown}"
echo "Effective LAB_ID: $LAB_ID"
echo

echo "=== Evidence Directory ==="
EVID_DIR="/evidence/tlog/$LAB_ID"
if [ -d "$EVID_DIR" ]; then
    echo "Directory exists: $EVID_DIR"
    ls -la "$EVID_DIR/" 2>/dev/null || echo "  (empty or unreadable)"
    if [ -f "$EVID_DIR/session.jsonl" ]; then
        echo "session.jsonl size: $(wc -c < "$EVID_DIR/session.jsonl") bytes"
        echo "session.jsonl lines: $(wc -l < "$EVID_DIR/session.jsonl")"
    else
        echo "session.jsonl: <not found>"
    fi
else
    echo "Directory missing: $EVID_DIR"
fi
echo

echo "=== Tlog Config ==="
CONF="/etc/tlog/tlog-rec-session.conf"
if [ -f "$CONF" ]; then
    echo "Config exists: $CONF ($(wc -c < "$CONF") bytes)"
    echo "log.input setting: $(grep -o '"input"[[:space:]]*:[[:space:]]*[a-z]*' "$CONF" || echo '<not found>')"
else
    echo "Config missing: $CONF"
fi
echo

echo "=== XFCE Terminal Config ==="
TERMRC="$HOME/.config/xfce4/terminal/terminalrc"
if [ -f "$TERMRC" ]; then
    echo "terminalrc exists: $TERMRC"
    echo "--- First 10 lines ---"
    head -n 10 "$TERMRC"
else
    echo "terminalrc missing: $TERMRC"
fi
echo

echo "=== Wrapper Log ==="
if [ -f /tmp/octobox-shell.log ]; then
    echo "Log exists: /tmp/octobox-shell.log ($(wc -l < /tmp/octobox-shell.log) lines)"
    echo "--- Last 10 lines ---"
    tail -n 10 /tmp/octobox-shell.log
else
    echo "Log missing: /tmp/octobox-shell.log"
fi
echo

echo "=== User Shell ==="
echo "pentester shell: $(getent passwd pentester | cut -d: -f7)"
echo

echo "=== Tlog Binary ==="
if command -v tlog-rec-session >/dev/null 2>&1; then
    echo "tlog-rec-session: $(which tlog-rec-session)"
    tlog-rec-session --version 2>&1 || echo "(version check failed)"
else
    echo "tlog-rec-session: <not found>"
fi
DEBUG_EOF

RUN chmod 0755 /usr/local/bin/octobox-debug-terminal

# Create immutable xstartup template that calls the XFCE launcher
# This is the authoritative version that gets copied at runtime
RUN cat > /etc/octobox/xstartup.template << 'XSTARTUP_EOF'
#!/bin/sh
# OctoBox xstartup - calls robust XFCE launcher
# This file is copied from /etc/octobox/xstartup.template at each boot
exec /usr/local/bin/octobox-xstartup
XSTARTUP_EOF

RUN chmod 0755 /etc/octobox/xstartup.template

# Make sure line endings are Unix and it's executable
RUN sed -i 's/\r$//' /home/${USERNAME}/startup.sh && chmod +x /home/${USERNAME}/startup.sh

EXPOSE ${NOVNC_PORT}
# Run entrypoint as root; it will switch to pentester user
ENTRYPOINT ["/entrypoint.sh"]
