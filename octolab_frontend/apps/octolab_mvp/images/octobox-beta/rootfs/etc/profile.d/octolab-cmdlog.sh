#!/bin/bash
# OctoLab command logging hook for interactive bash shells
# Canonical location: /etc/profile.d/octolab-cmdlog.sh
# Also sourced via /etc/bash.bashrc for non-login interactive shells (XFCE Terminal)
#
# To verify which build is running: cat /etc/octolab-cmdlog.build-id
#
# SECURITY:
# - Only activates for interactive shells
# - Validates session IDs strictly (UUID or alphanumeric)
# - Never writes outside /evidence/tlog/<sanitized_id>/
# - Fails closed: no writable dir = no logging (but hook stays installed)

# ----------------------------------------------------------------------------
# Early exit for non-interactive shells
# ----------------------------------------------------------------------------
case "$-" in
    *i*) ;;
    *) return 0 2>/dev/null || exit 0 ;;
esac

# ----------------------------------------------------------------------------
# Kill switch
# ----------------------------------------------------------------------------
if [[ -n "${OCTOLOG_DISABLE:-}" ]]; then
    return 0 2>/dev/null || exit 0
fi

# ----------------------------------------------------------------------------
# Idempotency: don't re-install if already done
# ----------------------------------------------------------------------------
if [[ -n "${OCTOLAB_CMDLOG_ENABLED:-}" ]]; then
    return 0 2>/dev/null || exit 0
fi

# ----------------------------------------------------------------------------
# Debug helper
# ----------------------------------------------------------------------------
__octolab_debug() {
    [[ -n "${OCTOLAB_CMDLOG_DEBUG:-}" ]] && echo "[octolab-cmdlog] $*" >&2 || true
}

# ----------------------------------------------------------------------------
# Validation regexes
# ----------------------------------------------------------------------------
__OCTOLAB_UUID_REGEX='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
__OCTOLAB_SAFE_ID_REGEX='^[A-Za-z0-9_-]+$'

# ----------------------------------------------------------------------------
# Global state
# ----------------------------------------------------------------------------
__OCTOLAB_LOG_DIR=""
__OCTOLAB_LAST_HISTCMD=0
__OCTOLAB_LOG_RUNNING=""

# ----------------------------------------------------------------------------
# Find writable log directory
# Returns: sets __OCTOLAB_LOG_DIR or leaves it empty
# ----------------------------------------------------------------------------
__octolab_resolve_log_dir() {
    # If already resolved and still writable, keep it
    if [[ -n "$__OCTOLAB_LOG_DIR" && -d "$__OCTOLAB_LOG_DIR" && -w "$__OCTOLAB_LOG_DIR" ]]; then
        return 0
    fi

    __OCTOLAB_LOG_DIR=""
    local candidate=""

    # Priority 1: OCTOLAB_SESSION_ID (must be valid UUID)
    if [[ -n "${OCTOLAB_SESSION_ID:-}" ]]; then
        if [[ "${OCTOLAB_SESSION_ID,,}" =~ $__OCTOLAB_UUID_REGEX ]]; then
            candidate="/evidence/tlog/${OCTOLAB_SESSION_ID}"
        else
            __octolab_debug "OCTOLAB_SESSION_ID='$OCTOLAB_SESSION_ID' failed UUID validation"
        fi
    fi

    # Priority 2: LAB_ID (must be safe alphanumeric)
    if [[ -z "$candidate" && -n "${LAB_ID:-}" ]]; then
        if [[ "$LAB_ID" =~ $__OCTOLAB_SAFE_ID_REGEX ]]; then
            candidate="/evidence/tlog/${LAB_ID}"
        else
            __octolab_debug "LAB_ID='$LAB_ID' failed safe-id validation"
        fi
    fi

    # Priority 3: Auto-detect single writable dir under /evidence/tlog/
    if [[ -z "$candidate" && -d "/evidence/tlog" ]]; then
        local dirs=()
        # Use nullglob to handle empty case
        local old_nullglob
        old_nullglob=$(shopt -p nullglob 2>/dev/null || echo "shopt -u nullglob")
        shopt -s nullglob
        dirs=(/evidence/tlog/*/)
        eval "$old_nullglob"

        if [[ ${#dirs[@]} -eq 1 && -d "${dirs[0]}" && -w "${dirs[0]}" ]]; then
            # Remove trailing slash for consistency
            candidate="${dirs[0]%/}"
            __octolab_debug "Auto-detected single writable dir: $candidate"
        elif [[ ${#dirs[@]} -gt 1 ]]; then
            __octolab_debug "Multiple dirs under /evidence/tlog/, cannot auto-detect"
        elif [[ ${#dirs[@]} -eq 0 ]]; then
            __octolab_debug "No dirs under /evidence/tlog/"
        fi
    fi

    # Attempt to create candidate directory if it doesn't exist
    # Only do this if we have a valid candidate from LAB_ID/OCTOLAB_SESSION_ID
    # (not auto-detected) and /evidence exists and is writable
    if [[ -n "$candidate" && ! -d "$candidate" ]]; then
        if [[ -d "/evidence" && -w "/evidence" ]]; then
            # Create intermediate dirs if needed, with secure permissions
            # Try install first (atomic, handles ownership), fallback to mkdir
            if command -v install >/dev/null 2>&1; then
                install -d -m 0700 "$candidate" 2>/dev/null && \
                    __octolab_debug "Created log dir via install: $candidate"
            else
                mkdir -p "$candidate" 2>/dev/null && \
                chmod 0700 "$candidate" 2>/dev/null && \
                    __octolab_debug "Created log dir via mkdir: $candidate"
            fi
        else
            __octolab_debug "/evidence not writable, cannot create $candidate"
        fi
    fi

    # Validate candidate is writable
    if [[ -n "$candidate" && -d "$candidate" && -w "$candidate" ]]; then
        __OCTOLAB_LOG_DIR="$candidate"
        __octolab_debug "Using log dir: $__OCTOLAB_LOG_DIR"
    elif [[ -n "$candidate" ]]; then
        __octolab_debug "Candidate '$candidate' not writable or doesn't exist"
    fi
}

# ----------------------------------------------------------------------------
# Sanitize command for TSV (replace tabs/newlines)
# ----------------------------------------------------------------------------
__octolab_sanitize_cmd() {
    local cmd="$1"
    # Replace tabs with spaces, newlines with literal \n
    cmd="${cmd//$'\t'/ }"
    cmd="${cmd//$'\n'/\\n}"
    printf '%s' "$cmd"
}

# ----------------------------------------------------------------------------
# Main logging function (called via PROMPT_COMMAND)
# ----------------------------------------------------------------------------
__octo_log_prompt() {
    # Re-entrancy guard (global)
    [[ -n "$__OCTOLAB_LOG_RUNNING" ]] && return 0
    __OCTOLAB_LOG_RUNNING=1

    # Ensure we unset guard on exit
    trap 'unset __OCTOLAB_LOG_RUNNING' RETURN

    # Skip if history is disabled
    if ! shopt -q -o history 2>/dev/null; then
        __octolab_debug "History disabled, skipping"
        return 0
    fi

    # Get current history number
    local current_histcmd="${HISTCMD:-0}"

    # Skip if same or earlier command (avoid duplicates)
    if [[ "$current_histcmd" -le "$__OCTOLAB_LAST_HISTCMD" ]]; then
        return 0
    fi

    # Get the last command from history
    local last_cmd
    last_cmd=$(fc -ln -1 2>/dev/null) || return 0
    # Trim leading whitespace
    last_cmd="${last_cmd#"${last_cmd%%[![:space:]]*}"}"

    # Skip if empty or is our own function
    if [[ -z "$last_cmd" || "$last_cmd" == *"__octo_log_prompt"* ]]; then
        __OCTOLAB_LAST_HISTCMD="$current_histcmd"
        return 0
    fi

    # Resolve log directory (may become available after shell start)
    __octolab_resolve_log_dir

    # If no writable log dir, just update histcmd and return
    if [[ -z "$__OCTOLAB_LOG_DIR" ]]; then
        __OCTOLAB_LAST_HISTCMD="$current_histcmd"
        return 0
    fi

    # Gather metadata
    local ts username cwd sanitized_cmd
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "unknown")
    username=$(id -un 2>/dev/null || echo "unknown")
    cwd="$PWD"
    sanitized_cmd=$(__octolab_sanitize_cmd "$last_cmd")

    # Write log with restricted umask
    local log_file="${__OCTOLAB_LOG_DIR}/commands.tsv"
    (
        umask 077
        printf '%s\t%s\t%s\t%s\n' "$ts" "$username" "$cwd" "$sanitized_cmd" >> "$log_file"
    ) 2>/dev/null || __octolab_debug "Failed to write to $log_file"

    # Update last histcmd
    __OCTOLAB_LAST_HISTCMD="$current_histcmd"
}

# ----------------------------------------------------------------------------
# Install into PROMPT_COMMAND (idempotent, supports string and array)
# ----------------------------------------------------------------------------
__octolab_install_prompt_command() {
    local pc_type
    pc_type=$(declare -p PROMPT_COMMAND 2>/dev/null) || pc_type=""

    # Check if already installed
    if [[ "$pc_type" == *"__octo_log_prompt"* ]]; then
        __octolab_debug "Already in PROMPT_COMMAND, skipping install"
        return 0
    fi
    if [[ "${PROMPT_COMMAND:-}" == *"__octo_log_prompt"* ]]; then
        __octolab_debug "Already in PROMPT_COMMAND string, skipping install"
        return 0
    fi

    # Handle array format (bash 5.1+ / VTE)
    if [[ "$pc_type" == "declare -a"* ]]; then
        __octolab_debug "PROMPT_COMMAND is array, prepending"
        PROMPT_COMMAND=("__octo_log_prompt" "${PROMPT_COMMAND[@]}")
    elif [[ -z "${PROMPT_COMMAND:-}" ]]; then
        __octolab_debug "PROMPT_COMMAND empty, setting"
        PROMPT_COMMAND="__octo_log_prompt"
    else
        __octolab_debug "PROMPT_COMMAND is string, prepending"
        PROMPT_COMMAND="__octo_log_prompt;${PROMPT_COMMAND}"
    fi

    export PROMPT_COMMAND
}

# ----------------------------------------------------------------------------
# Main: install the hook
# ----------------------------------------------------------------------------
__octolab_install_prompt_command
export OCTOLAB_CMDLOG_ENABLED=1

__octolab_debug "Command logging hook installed"
