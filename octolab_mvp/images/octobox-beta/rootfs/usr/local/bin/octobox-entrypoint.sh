#!/usr/bin/env bash

set -e

echo "OctoBox Beta: Starting..."

# Ensure evidence directory exists and is owned by pentester
mkdir -p /evidence
chown pentester:pentester /evidence || true
chmod 755 /evidence || true

# Ensure X11 socket directory exists with proper permissions
# Xorg creates sockets in /tmp/.X11-unix for display communication
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix || true

# Ensure pentester home directory is writable for Xorg logs and sockets
# Xorg writes logs to ~/.xorgxrdp.*.log and may create additional files
chown -R pentester:pentester /home/pentester || true
chmod 755 /home/pentester || true

# Start DBus (needed for XFCE)
# In containers, use session bus instead of system bus.
# Note: XRDP sessions will also start their own per-session DBus via dbus-launch
# in /etc/xrdp/startwm.sh. This DBus instance here is for any system-level usage.
if command -v dbus-daemon >/dev/null 2>&1; then
  echo "Starting DBus (session bus)..."
  mkdir -p /var/run/dbus
  dbus-daemon --session --fork || true
else
  echo "Warning: dbus-daemon not found, XFCE may misbehave" >&2
fi

# XRDP runtime dirs
mkdir -p /var/run/xrdp /var/log/xrdp
chown -R xrdp:xrdp /var/run/xrdp /var/log/xrdp || true
chmod 755 /var/log/xrdp || true  # Ensure logs can be written

# Debug: Print XRDP version and package info
echo "XRDP version:"
xrdp --version || true
echo "Installed XRDP/Xorg packages:"
dpkg -l xrdp xorgxrdp || true
echo "XRDP config snippets:"
sed -n '1,80p' /etc/xrdp/sesman.ini || true
sed -n '1,80p' /etc/xrdp/xrdp.ini || true

echo "Starting xrdp-sesman..."
/usr/sbin/xrdp-sesman --nodaemon &
SESMAN_PID=$!

echo "Starting xrdp..."
/usr/sbin/xrdp --nodaemon &
XRDP_PID=$!

sleep 2

echo "OctoBox Beta: Services started"
echo "  - xrdp-sesman PID: ${SESMAN_PID}"
echo "  - xrdp PID: ${XRDP_PID}"
echo "  - RDP port: 3389"
echo "  - Evidence directory: /evidence"
echo "Network interfaces:"
ip addr show || true

echo "OctoBox Beta: XRDP processes:"
ps aux | grep -E 'xrdp|Xorg' | grep -v grep || true

echo "OctoBox Beta: Socket diagnostics:"
ls -la /tmp/.X11-unix/ 2>/dev/null || echo "No X11 sockets yet"
ss -lx | grep -E 'xrdp|X10' || echo "No xrdp/X11 UNIX sockets yet"
ss -tlnp | grep -E '3389|600' || echo "No TCP X/RDP listeners visible yet"

echo "OctoBox Beta: Ready. Waiting for XRDP processes to exit..."
wait

