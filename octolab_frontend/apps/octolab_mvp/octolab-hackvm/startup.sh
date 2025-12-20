#!/bin/bash
set -e

export USER=pentester
export HOME=/home/pentester
export DISPLAY=:0
export VNC_PORT=5900
export NOVNC_PORT=6080

# VNC auth mode: "password" (default) or "none" (localhost-only, checked by backend)
VNC_AUTH_MODE="${OCTOBOX_VNC_AUTH:-password}"

# GUAC mode: when GUAC_ENABLED=true, bind VNC to all interfaces (0.0.0.0) for guacd access
# In GUAC mode, guacd connects directly to VNC, and noVNC is not started
# SECURITY: GUAC mode REQUIRES a VNC password (OCTOBOX_VNC_PASSWORD must be set)
GUAC_MODE="${GUAC_ENABLED:-false}"
if [ "$GUAC_MODE" = "true" ] || [ "$GUAC_MODE" = "1" ]; then
    # SECURITY: In GUAC mode, VNC is exposed on the network, so password is REQUIRED
    if [ -z "${OCTOBOX_VNC_PASSWORD:-}" ]; then
        echo "SECURITY ERROR: GUAC mode requires OCTOBOX_VNC_PASSWORD to be set" >&2
        echo "Cannot start VNC without authentication on network interface" >&2
        exit 1
    fi
    echo "GUAC mode enabled: VNC will bind to 0.0.0.0:${VNC_PORT} with password auth, noVNC will NOT start" >&2
    VNC_LISTEN_ALL=true
    # In GUAC mode, always force password auth regardless of VNC_AUTH_MODE setting
    VNC_AUTH_MODE="password"
else
    echo "Standard mode: VNC on localhost, noVNC enabled" >&2
    VNC_LISTEN_ALL=false
fi

# Marker file to prevent repeated diagnostic dumps in restart loops
DIAG_MARKER="/tmp/.octobox_diag_dumped"

# Function to dump diagnostics once on failure
dump_diagnostics() {
    if [ -f "$DIAG_MARKER" ]; then
        echo "Diagnostics already dumped (see earlier logs)" >&2
        return
    fi
    touch "$DIAG_MARKER"
    echo "=== OctoBox VNC Startup Diagnostics ===" >&2
    echo "--- VNC log (last 100 lines) ---" >&2
    tail -n 100 "$HOME/.vnc/"*:1.log 2>/dev/null || echo "(no VNC log)" >&2
    echo "--- xstartup.log (last 100 lines) ---" >&2
    tail -n 100 "$HOME/.vnc/xstartup.log" 2>/dev/null || echo "(no xstartup.log)" >&2
    echo "--- Processes ---" >&2
    ps aux 2>/dev/null || true
    echo "=== End Diagnostics ===" >&2
}

# Cleanup diagnostics marker on fresh start
rm -f "$DIAG_MARKER"

mkdir -p "$HOME/.vnc"
chmod 700 "$HOME/.vnc"

# Create .Xresources file to prevent xrdb errors
touch "$HOME/.Xresources"

# Initialize xstartup.log for the XFCE launcher
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === VNC session starting ===" > "$HOME/.vnc/xstartup.log"

# Configure VNC authentication based on mode
if [ "$VNC_AUTH_MODE" = "none" ]; then
  echo "VNC auth mode: none (passwordless - localhost only)" >&2
  # Remove any existing password file
  rm -f "$HOME/.vnc/passwd"
  VNC_SECURITY_TYPE="-SecurityTypes None"
else
  echo "VNC auth mode: password" >&2
  VNC_SECURITY_TYPE=""

  # Determine which password to use:
  # - GUAC mode: ALWAYS use OCTOBOX_VNC_PASSWORD (required, validated above)
  # - Standard mode: Use OCTOBOX_VNC_PASSWORD if set, otherwise use default
  if [ -n "${OCTOBOX_VNC_PASSWORD:-}" ]; then
    VNC_PASSWORD="$OCTOBOX_VNC_PASSWORD"
    echo "Using provided VNC password" >&2
  else
    VNC_PASSWORD="octo123"
    echo "Using default VNC password (standard mode only)" >&2
  fi

  # Always regenerate password file (don't rely on volume state)
  rm -f "$HOME/.vnc/passwd" 2>/dev/null || true

  # Use tigervncpasswd (for tigervnc-standalone-server) or fallback to vncpasswd
  # SECURITY: Never log the password
  if command -v tigervncpasswd >/dev/null 2>&1; then
    printf '%s\n' "$VNC_PASSWORD" | tigervncpasswd -f > "$HOME/.vnc/passwd"
  elif command -v vncpasswd >/dev/null 2>&1; then
    printf '%s\n' "$VNC_PASSWORD" | vncpasswd -f > "$HOME/.vnc/passwd"
  else
    echo "ERROR: Neither tigervncpasswd nor vncpasswd found" >&2
    exit 1
  fi
  chmod 600 "$HOME/.vnc/passwd"

  # Clear password from environment after use (defense in depth)
  unset VNC_PASSWORD
fi

# Configure xfce4-terminal BEFORE creating xstartup
# Create terminalrc file directly (not in xstartup) so it exists before XFCE starts
# Use tlog-rec-session for structured JSONL logging (configured in entrypoint.sh)
mkdir -p "$HOME/.config/xfce4/terminal"
echo "Command=/usr/bin/tlog-rec-session" > "$HOME/.config/xfce4/terminal/terminalrc"
echo "UseCustomCommand=true" >> "$HOME/.config/xfce4/terminal/terminalrc"
echo "LoginShell=true" >> "$HOME/.config/xfce4/terminal/terminalrc"
chmod 644 "$HOME/.config/xfce4/terminal/terminalrc"

# Also ensure .bashrc sources the logging script (PROMPT_COMMAND fallback for non-tlog terminals)
if ! grep -q "octolog.sh" "$HOME/.bashrc" 2>/dev/null; then
    echo "" >> "$HOME/.bashrc"
    echo "# Source command logging (PROMPT_COMMAND fallback)" >> "$HOME/.bashrc"
    echo "[ -f /etc/profile.d/octolog.sh ] && source /etc/profile.d/octolog.sh" >> "$HOME/.bashrc"
fi

# Always update xstartup - copy immutable template from image to prevent state drift
# Architecture: xstartup is authoritative in the image, copied at runtime to prevent tenant modification
# Template is stored in /etc/octobox to avoid volume mount conflicts
# This ensures we always use a known-good version, not whatever is in the persistent volume
# CRITICAL: Remove old xstartup first, then copy template (volume may have old version)
echo "=== Copying xstartup template from image ===" >&2
rm -f "$HOME/.vnc/xstartup" "$HOME/.vnc/xstartup.bak" 2>/dev/null || true
if [ -f "/etc/octobox/xstartup.template" ]; then
    echo "Template found at /etc/octobox/xstartup.template" >&2
    cp -f /etc/octobox/xstartup.template "$HOME/.vnc/xstartup" || { echo "ERROR: Copy failed!" >&2; exit 1; }
    chmod +x "$HOME/.vnc/xstartup" || { echo "ERROR: chmod failed!" >&2; exit 1; }
    # Verify the copy worked (should call octobox-xstartup)
    if grep -q "octobox-xstartup" "$HOME/.vnc/xstartup" 2>/dev/null; then
        echo "SUCCESS: xstartup copied and verified" >&2
    else
        echo "ERROR: xstartup copy verification failed!" >&2
        cat "$HOME/.vnc/xstartup" >&2
        exit 1
    fi
else
    # Fallback if template missing (shouldn't happen, but be defensive)
    echo "WARNING: xstartup.template not found at /etc/octobox/xstartup.template, using fallback" >&2
    cat > "$HOME/.vnc/xstartup" << 'EOF'
#!/bin/sh
# Fallback xstartup - try XFCE launcher, fall back to xterm
if [ -x /usr/local/bin/octobox-xstartup ]; then
    exec /usr/local/bin/octobox-xstartup
fi
# Ultimate fallback: xterm
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
[ -f "$HOME/.Xresources" ] && xrdb "$HOME/.Xresources" 2>/dev/null || true
xsetroot -solid grey 2>/dev/null || true
exec /usr/bin/xterm -geometry 120x40+10+10 -ls -title "OctoBox VNC"
EOF
    chmod +x "$HOME/.vnc/xstartup"
fi
echo "xstartup ready, starting VNC server..." >&2

# Start VNC server with configured security type (None for passwordless, VncAuth for password)
# In GUAC mode, bind to all interfaces so guacd can connect from lab_net
# Capture startup output to detect early failures
echo "Starting VNC server on $DISPLAY..." >&2

# Build VNC options
VNC_OPTS="-geometry 1280x800 -depth 24"
if [ "$VNC_LISTEN_ALL" = "true" ]; then
    # -localhost no allows connections from any interface (needed for guacd on lab_net)
    VNC_OPTS="$VNC_OPTS -localhost no"
    echo "VNC: binding to 0.0.0.0 (all interfaces)" >&2
fi

# shellcheck disable=SC2086
VNC_OUTPUT=$(vncserver "$DISPLAY" $VNC_OPTS $VNC_SECURITY_TYPE 2>&1) || {
    echo "ERROR: VNC server failed to start!" >&2
    echo "$VNC_OUTPUT" >&2
    dump_diagnostics
    exit 1
}

# Check for "xstartup exited too early" in output or log
sleep 1  # Give VNC a moment to initialize
VNC_LOG="$HOME/.vnc/$(hostname):1.log"
if echo "$VNC_OUTPUT" | grep -q "exited too early"; then
    echo "ERROR: xstartup exited too early (detected in output)" >&2
    dump_diagnostics
    exit 1
fi
if [ -f "$VNC_LOG" ] && grep -q "exited too early" "$VNC_LOG" 2>/dev/null; then
    echo "ERROR: xstartup exited too early (detected in log)" >&2
    dump_diagnostics
    exit 1
fi
echo "VNC server started successfully on $DISPLAY" >&2

# Also configure via xfconf as a backup (runs after XFCE starts)
# This ensures the config is set even if terminalrc is overwritten
configure_xfce_terminal() {
  # Wait for xfconfd to be ready (up to 10 seconds with longer initial wait)
  sleep 3  # Give XFCE more time to start
  for i in 1 2 3 4 5 6 7; do
    if xfconf-query -c xfce4-terminal -l >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  # Configure xfce4-terminal to use tlog-rec-session for structured JSONL logging
  # XFCE Terminal 4.x uses /profiles/default/ paths, not /general/

  # Set custom command
  xfconf-query -c xfce4-terminal -n -t string -p /profiles/default/command \
    -s "/usr/bin/tlog-rec-session" 2>/tmp/xfconf-err.log || \
  xfconf-query -c xfce4-terminal -t string -p /profiles/default/command \
    -s "/usr/bin/tlog-rec-session" 2>>/tmp/xfconf-err.log || true

  # Enable use of custom command
  xfconf-query -c xfce4-terminal -n -t bool -p /profiles/default/use-custom-command \
    -s true 2>>/tmp/xfconf-err.log || \
  xfconf-query -c xfce4-terminal -t bool -p /profiles/default/use-custom-command \
    -s true 2>>/tmp/xfconf-err.log || true

  # Enable login shell (if property exists)
  xfconf-query -c xfce4-terminal -n -t bool -p /profiles/default/login-shell \
    -s true 2>>/tmp/xfconf-err.log || \
  xfconf-query -c xfce4-terminal -t bool -p /profiles/default/login-shell \
    -s true 2>>/tmp/xfconf-err.log || true

  # Also try /general/ paths as fallback (some versions use these)
  xfconf-query -c xfce4-terminal -n -t string -p /general/custom-command \
    -s "/usr/bin/tlog-rec-session" 2>>/tmp/xfconf-err.log || \
  xfconf-query -c xfce4-terminal -t string -p /general/custom-command \
    -s "/usr/bin/tlog-rec-session" 2>>/tmp/xfconf-err.log || true

  xfconf-query -c xfce4-terminal -n -t bool -p /general/use-custom-command \
    -s true 2>>/tmp/xfconf-err.log || \
  xfconf-query -c xfce4-terminal -t bool -p /general/use-custom-command \
    -s true 2>>/tmp/xfconf-err.log || true
}

# Run xfconf configuration in background after XFCE has started
configure_xfce_terminal &

# In GUAC mode, skip noVNC entirely - guacd connects directly to VNC
if [ "$VNC_LISTEN_ALL" = "true" ]; then
    echo "GUAC mode: noVNC disabled, waiting indefinitely..." >&2
    echo "VNC is available at 0.0.0.0:${VNC_PORT} for guacd" >&2
    # Keep the container running (VNC server is the main process in background)
    # Use a simple wait loop that responds to signals
    trap 'echo "Received signal, exiting..."; exit 0' SIGTERM SIGINT
    while true; do
        sleep 60
    done
else
    # Standard mode: start noVNC for browser-based access
    NOVNC_DIR="/usr/share/novnc"
    if [ ! -d "$NOVNC_DIR" ]; then
        echo "noVNC not found in $NOVNC_DIR"
        ls -lah /usr/share
    fi

    echo "Starting noVNC on port ${NOVNC_PORT}, proxying to VNC ${VNC_PORT}"
    websockify --web "${NOVNC_DIR}" "${NOVNC_PORT}" localhost:"${VNC_PORT}"
fi
