#!/bin/bash
# PROMPT_COMMAND-based command logging (backup method)
# This is a proven, reliable fallback that works even if script command fails
# Based on proven methods used in production environments

# Only set up logging if not already disabled and if /evidence is writable
if [ -n "$OCTOLOG_DISABLE" ] || [ ! -w /evidence ] 2>/dev/null; then
    return 0 2>/dev/null || true
fi

# Ensure /evidence exists and is writable
mkdir -p /evidence
if [ ! -w /evidence ]; then
    return 0 2>/dev/null || true
fi

# Track the last command number to avoid duplicate logging
__OCTO_LAST_HISTNUM="${__OCTO_LAST_HISTNUM:-0}"

# Function to log commands via PROMPT_COMMAND
# This method is proven to work reliably in Docker containers
__octo_log_prompt() {
    # Skip if history is not enabled
    if ! set -o | grep -q "history.*on"; then
        return 0
    fi
    
    # Get current history number
    local current_histnum="${HISTCMD:-0}"
    
    # Skip if this is the same or earlier command (avoid duplicates)
    if [ "$current_histnum" -le "$__OCTO_LAST_HISTNUM" ]; then
        return 0
    fi
    
    # Get the last command from history using fc (more reliable than history command)
    local last_cmd
    last_cmd=$(fc -ln -1 2>/dev/null | sed 's/^[[:space:]]*//' || echo "")
    
    # Skip if empty or is our logging function
    if [ -z "$last_cmd" ] || [[ "$last_cmd" == *"__octo_log_prompt"* ]] || [[ "$last_cmd" == *"__octo_log"* ]]; then
        __OCTO_LAST_HISTNUM="$current_histnum"
        return 0
    fi
    
    # Get ISO8601 timestamp
    local timestamp
    timestamp=$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null || echo "")
    
    # Get username and working directory
    local username="${USER:-$(whoami 2>/dev/null || echo "unknown")}"
    local cwd="${PWD:-$(pwd 2>/dev/null || echo "unknown")}"
    
    # Log to file (append, non-blocking)
    # Format: <ISO8601 timestamp>\t<username>\t<cwd>\t<command>
    printf "%s\t%s\t%s\t%s\n" "$timestamp" "$username" "$cwd" "$last_cmd" >> /evidence/commands.log 2>/dev/null || true
    
    # Update last history number
    __OCTO_LAST_HISTNUM="$current_histnum"
}

# Wire into PROMPT_COMMAND (preserve existing if any)
# This is the proven method that works in all bash sessions
if [ -z "$PROMPT_COMMAND" ]; then
    export PROMPT_COMMAND="__octo_log_prompt"
else
    # Prepend our function, preserving existing
    export PROMPT_COMMAND="__octo_log_prompt;$PROMPT_COMMAND"
fi

# Enable history (required for PROMPT_COMMAND logging to work)
export HISTFILE="${HISTFILE:-$HOME/.bash_history}"
export HISTSIZE="${HISTSIZE:-1000}"
export HISTFILESIZE="${HISTFILESIZE:-2000}"
export HISTCONTROL="${HISTCONTROL:-ignoredups:erasedups}"
set -o history
