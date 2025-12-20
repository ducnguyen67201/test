#!/bin/bash
# LEGACY: unused since script-based octolog-shell logging (evidence v2.0).
# This file is kept for reference only.
#
# OctoBox Command Logging Hook
# Logs all commands executed by users to /evidence/commands.log

# Ensure bash history is enabled
export HISTFILE="${HISTFILE:-$HOME/.bash_history}"
export HISTSIZE="${HISTSIZE:-1000}"
export HISTFILESIZE="${HISTFILESIZE:-2000}"
export HISTCONTROL="${HISTCONTROL:-ignoredups:erasedups}"

# Enable history (required for history command to work)
set -o history

# Track the last command number to avoid duplicate logging
__OCTO_LAST_HISTNUM="${__OCTO_LAST_HISTNUM:-0}"

# Function to log the last command
__octo_log_command() {
    # Skip if this is the first prompt (no command executed yet)
    local current_histnum="${HISTCMD:-0}"
    if [ "$current_histnum" -le "$__OCTO_LAST_HISTNUM" ]; then
        return 0
    fi
    
    # Get the last command from history using fc (more reliable than history command)
    local last_cmd
    last_cmd=$(fc -ln -1 2>/dev/null | sed 's/^[[:space:]]*//' || echo "")
    
    # Skip if command is empty or is our logging function itself
    if [ -z "$last_cmd" ] || [ "$last_cmd" = "__octo_log_command" ] || [[ "$last_cmd" == *"__octo_log_command"* ]]; then
        __OCTO_LAST_HISTNUM="$current_histnum"
        return 0
    fi
    
    # Get ISO8601 timestamp
    local timestamp
    timestamp=$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null || echo "")
    
    # Get username
    local username
    username="${USER:-$(whoami 2>/dev/null || echo "unknown")}"
    
    # Get current working directory
    local cwd
    cwd="${PWD:-$(pwd 2>/dev/null || echo "unknown")}"
    
    # Log to file (append, non-blocking)
    # Format: <ISO8601 timestamp>\t<username>\t<cwd>\t<command>
    printf "%s\t%s\t%s\t%s\n" "$timestamp" "$username" "$cwd" "$last_cmd" >> /evidence/commands.log 2>/dev/null || true
    
    # Update last history number
    __OCTO_LAST_HISTNUM="$current_histnum"
}

# Wire into PROMPT_COMMAND safely (preserve existing PROMPT_COMMAND if any)
PROMPT_COMMAND="__octo_log_command${PROMPT_COMMAND:+;$PROMPT_COMMAND}"

