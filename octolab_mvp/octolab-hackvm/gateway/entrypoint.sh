#!/bin/bash

# LabGateway entrypoint: NAT routing + network capture (PCAP + JSON)
# Runs as root with NET_ADMIN + NET_RAW capabilities
# Writes authoritative evidence to /evidence/auth/network/

set -euo pipefail

# Enable IPv4 forwarding (required for NAT)
# If this fails (e.g., permission issue), warn but don't crash
if ! sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1; then
    echo "Warning: Failed to enable IPv4 forwarding (may need NET_ADMIN capability)" >&2
fi

# Determine WAN interface (uplink - has default route)
WAN_IFACE=$(ip route show default | awk '/default/ {print $5}' | head -n1)

# Fail fast if WAN interface cannot be detected
if [ -z "$WAN_IFACE" ]; then
    echo "Error: Cannot determine WAN interface (no default route found)" >&2
    exit 1
fi

# Strip Docker's @if* suffix from interface name (e.g., eth0@if152 -> eth0)
WAN_IFACE="${WAN_IFACE%%@*}"

echo "Selected WAN interface: $WAN_IFACE"

# Determine LAN interface
if [ -n "${LAB_LAN_IFACE:-}" ]; then
    # Use explicitly specified LAN interface
    LAN_IFACE="$LAB_LAN_IFACE"
else
    # Find any interface that is NOT the WAN interface
    # Get all interfaces except lo and the WAN interface
    LAN_IFACE=$(ip -o link show | awk -F': ' '{print $2}' | grep -v "^lo$" | grep -v "^${WAN_IFACE}$" | head -n1)

    # Fallback: if only one interface exists (dev-only case), use it for both
    if [ -z "$LAN_IFACE" ]; then
        LAN_IFACE="$WAN_IFACE"
    fi
fi

# Fail fast if LAN interface cannot be determined
if [ -z "$LAN_IFACE" ]; then
    echo "Error: Cannot determine LAN interface" >&2
    exit 1
fi

# Strip Docker's @if* suffix from interface name (e.g., eth0@if152 -> eth0)
LAN_IFACE="${LAN_IFACE%%@*}"

echo "Selected LAN interface: $LAN_IFACE"

# Configure NAT (MASQUERADE on WAN interface)
iptables -t nat -A POSTROUTING -o "$WAN_IFACE" -j MASQUERADE

# Ensure output directories exist
# /evidence/auth is mounted from the evidence_auth volume
# /pcap is mounted from the lab_pcap volume
mkdir -p /evidence/auth/network /pcap

# Define output paths (deterministic, in mounted volumes)
# Authoritative evidence goes to /evidence/auth/network/
PCAP_FILE="/pcap/capture.pcap"
JSON_FILE="/evidence/auth/network/network.json"

echo "Starting network capture on $LAN_IFACE"
echo "  PCAP: $PCAP_FILE"
echo "  JSON (authoritative): $JSON_FILE"

# Start tcpdump for PCAP capture in background
# -U: packet-buffered output (write each packet as it's captured)
# -w: write raw packets to file
tcpdump -i "$LAN_IFACE" -U -w "$PCAP_FILE" 2>/dev/null &
TCPDUMP_PID=$!

# Cleanup function for graceful shutdown
cleanup() {
    echo "Shutting down capture processes..."
    kill "$TCPDUMP_PID" 2>/dev/null || true
    wait "$TCPDUMP_PID" 2>/dev/null || true
    echo "Capture stopped. PCAP saved to $PCAP_FILE"
}
trap cleanup SIGTERM SIGINT

# Determine TShark output format
# Try -T ek first (Elastic-style JSON), fall back to -T json if not available
if tshark -T help 2>&1 | grep -q "^\s*ek\s"; then
    TSHARK_FORMAT="ek"
    echo "Using TShark Elastic-style JSON format (-T ek)"
else
    TSHARK_FORMAT="json"
    echo "Using TShark JSON format (-T json)"
fi

# Start tshark for JSON output (foreground, becomes PID 1 child)
# -l: line buffering for real-time output
# Runs until container stops or signal received
tshark -i "$LAN_IFACE" -l -T "$TSHARK_FORMAT" >> "$JSON_FILE" &
TSHARK_PID=$!

# Wait for either process to exit
wait -n "$TCPDUMP_PID" "$TSHARK_PID" 2>/dev/null || true

# If we get here, one process died - cleanup and exit
cleanup
exit 0
