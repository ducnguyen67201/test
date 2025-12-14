#!/bin/bash
# LEGACY: unused since script-based octolog-shell logging (evidence v2.0).
# This file is kept for reference only.
#
# Wrapper shell that logs all terminal activity via script command

# Prevent infinite recursion if $SHELL=/usr/local/bin/octolog-shell
if [ -n "$OCTOLOG_DISABLE" ]; then
  exec /bin/bash "$@"
fi

# Ensure /evidence exists and is writable
mkdir -p /evidence
chmod 777 /evidence 2>/dev/null || true

# Test if script command is available
if ! command -v script >/dev/null 2>&1; then
  # Fallback to regular bash if script is not available
  exec /bin/bash "$@"
fi

# Use script command to log all terminal activity
# -q: quiet mode (no "Script started/ended" messages)
# -f: flush output immediately
# -a: append mode (don't overwrite existing log)
# Handle -c flag (run command) like a normal shell would
if [ "$1" = "-c" ] && [ $# -ge 2 ]; then
  # Called with -c "command": run the command via script
  shift  # Remove -c
  CMD="$*"
  exec script -q -f -a /evidence/commands.log -c "$CMD" 2>/dev/null
elif [ $# -eq 0 ]; then
  # No arguments: interactive shell
  exec script -q -f -a /evidence/commands.log /bin/bash 2>/dev/null
else
  # Other arguments: pass through to bash
  exec script -q -f -a /evidence/commands.log /bin/bash "$@" 2>/dev/null
fi

