#!/bin/bash
# This entrypoint runs as root to fix permissions, configure tlog, then switches to the user

set -euo pipefail

# ============================================================================
# Step 1: Resolve and validate LAB_ID
# ============================================================================
# Priority: OCTOLAB_LAB_ID env > LAB_ID env > /etc/octobox/lab_id file > "unknown"
LAB_ID="${OCTOLAB_LAB_ID:-${LAB_ID:-}}"

if [ -z "$LAB_ID" ] || [ "$LAB_ID" = "default" ]; then
    if [ -f /etc/octobox/lab_id ]; then
        LAB_ID="$(cat /etc/octobox/lab_id 2>/dev/null | tr -d '[:space:]')"
    fi
fi

# Default if still empty
if [ -z "$LAB_ID" ]; then
    LAB_ID="unknown"
    echo "WARNING: LAB_ID not set, using 'unknown' for tlog path" >&2
fi

# Validate LAB_ID for path safety: only allow [a-fA-F0-9-], max 64 chars
# This prevents path traversal attacks from hostile tenants
if ! echo "$LAB_ID" | grep -qE '^[a-fA-F0-9-]{1,64}$'; then
    echo "WARNING: LAB_ID contains invalid characters, using 'unknown'" >&2
    LAB_ID="unknown"
fi

# ============================================================================
# Step 2: Persist LAB_ID to filesystem for wrapper to read
# ============================================================================
mkdir -p /etc/octobox
echo -n "$LAB_ID" > /etc/octobox/lab_id
chmod 0644 /etc/octobox/lab_id
echo "Prepared lab_id=$LAB_ID"

# ============================================================================
# Step 3: Prepare evidence directory
# ============================================================================
mkdir -p /evidence
chmod 755 /evidence

TLOG_DIR="/evidence/tlog/${LAB_ID}"
mkdir -p "$TLOG_DIR"
chown -R pentester:pentester "$TLOG_DIR"
chmod 0770 "$TLOG_DIR"
echo "Prepared tlog dir: $TLOG_DIR"

# ============================================================================
# Step 4: Create wrapper log file with correct permissions
# ============================================================================
touch /tmp/octobox-shell.log
chown pentester:pentester /tmp/octobox-shell.log
chmod 0644 /tmp/octobox-shell.log

# ============================================================================
# Step 5: Generate tlog-rec-session config
# ============================================================================
# SECURITY: log.input=false prevents capturing passwords/tokens
mkdir -p /etc/tlog
cat > /etc/tlog/tlog-rec-session.conf << TLOG_CONF_EOF
{
    "shell": "/bin/bash",
    "writer": "file",
    "file": {
        "path": "${TLOG_DIR}/session.jsonl"
    },
    "log": {
        "input": false,
        "output": true,
        "window": true
    },
    "limit": {
        "rate": 16384,
        "burst": 32768,
        "action": "drop"
    }
}
TLOG_CONF_EOF
chmod 0644 /etc/tlog/tlog-rec-session.conf
echo "tlog config written (log.input=false)"

# ============================================================================
# Step 6: Export environment and switch to pentester user
# ============================================================================
# Export LAB_ID for any child processes
export OCTOLAB_LAB_ID="$LAB_ID"
export TLOG_OUTPUT_DIR="$TLOG_DIR"

# Switch to the pentester user and run the startup script
# Use runuser with --preserve-environment to pass OCTOLAB_LAB_ID
if command -v runuser >/dev/null 2>&1; then
    exec runuser --preserve-environment -u pentester -- /home/pentester/startup.sh
else
    exec su pentester -c "OCTOLAB_LAB_ID='$LAB_ID' TLOG_OUTPUT_DIR='$TLOG_DIR' /home/pentester/startup.sh"
fi
