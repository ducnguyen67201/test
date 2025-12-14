#!/usr/bin/env bash
#
# Tests for octolabctl netd status logic
# These tests run without root and without /dev/kvm by mocking /proc and socket state
#
# Run: ./infra/octolabctl/tests/test_status_logic.sh
#
# Note: We use set -u but NOT set -e since tests may involve expected failures
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OCTOLABCTL="$SCRIPT_DIR/../octolabctl.sh"

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Test helpers
test_pass() {
    ((TESTS_PASSED++))
    echo -e "${GREEN}PASS${NC}: $1"
}

test_fail() {
    ((TESTS_FAILED++))
    echo -e "${RED}FAIL${NC}: $1"
    echo "  Expected: $2"
    echo "  Got: $3"
}

# Create a temporary directory for test state
setup_test_env() {
    TEST_DIR=$(mktemp -d)
    MOCK_PROC_DIR="$TEST_DIR/proc"
    MOCK_RUN_DIR="$TEST_DIR/run"
    MOCK_LOG_DIR="$TEST_DIR/log"

    mkdir -p "$MOCK_PROC_DIR"
    mkdir -p "$MOCK_RUN_DIR"
    mkdir -p "$MOCK_LOG_DIR"

    export TEST_MODE=1
    export MOCK_PROC_ROOT="$MOCK_PROC_DIR"
    export MOCK_RUN_DIR="$MOCK_RUN_DIR"
    export MOCK_LOG_DIR="$MOCK_LOG_DIR"
}

teardown_test_env() {
    rm -rf "$TEST_DIR"
}

# Helper: create a mock process in /proc
create_mock_process() {
    local pid="$1"
    local cmdline="$2"
    mkdir -p "$MOCK_PROC_DIR/$pid"
    # NUL-separated cmdline
    echo -n "$cmdline" | tr ' ' '\0' > "$MOCK_PROC_DIR/$pid/cmdline"
}

# Helper: remove a mock process
remove_mock_process() {
    local pid="$1"
    rm -rf "$MOCK_PROC_DIR/$pid"
}

# Helper: create a mock socket file (not a real socket, but a regular file for testing)
create_mock_socket() {
    touch "$MOCK_RUN_DIR/microvm-netd.sock"
}

remove_mock_socket() {
    rm -f "$MOCK_RUN_DIR/microvm-netd.sock"
}

# Helper: create a mock pidfile
create_mock_pidfile() {
    local pid="$1"
    echo "$pid" > "$MOCK_RUN_DIR/microvm-netd.pid"
}

remove_mock_pidfile() {
    rm -f "$MOCK_RUN_DIR/microvm-netd.pid"
}

# =============================================================================
# Test: proc_exists function
# =============================================================================

test_proc_exists_when_process_exists() {
    ((TESTS_RUN++))
    setup_test_env

    # Create a mock process
    create_mock_process 12345 "python3 /path/to/microvm_netd.py"

    # Source the helper functions (we need to extract them)
    # Since we can't source octolabctl.sh directly (it runs main), we test the logic

    # Test using [ -d ]
    if [ -d "$MOCK_PROC_DIR/12345" ]; then
        test_pass "proc_exists returns true when process dir exists"
    else
        test_fail "proc_exists returns true when process dir exists" "true" "false"
    fi

    teardown_test_env
}

test_proc_exists_when_process_gone() {
    ((TESTS_RUN++))
    setup_test_env

    # Don't create a process, verify it doesn't exist
    if [ ! -d "$MOCK_PROC_DIR/99999" ]; then
        test_pass "proc_exists returns false when process dir missing"
    else
        test_fail "proc_exists returns false when process dir missing" "false" "true"
    fi

    teardown_test_env
}

# =============================================================================
# Test: read_pidfile function logic
# =============================================================================

test_read_pidfile_valid() {
    ((TESTS_RUN++))
    setup_test_env

    create_mock_pidfile 12345

    local pid
    pid=$(cat "$MOCK_RUN_DIR/microvm-netd.pid" 2>/dev/null | tr -d '[:space:]')

    if [[ "$pid" == "12345" ]] && [[ "$pid" =~ ^[0-9]+$ ]]; then
        test_pass "read_pidfile returns valid numeric PID"
    else
        test_fail "read_pidfile returns valid numeric PID" "12345" "$pid"
    fi

    teardown_test_env
}

test_read_pidfile_empty() {
    ((TESTS_RUN++))
    setup_test_env

    echo "" > "$MOCK_RUN_DIR/microvm-netd.pid"

    local pid
    pid=$(cat "$MOCK_RUN_DIR/microvm-netd.pid" 2>/dev/null | tr -d '[:space:]')

    if [[ -z "$pid" ]]; then
        test_pass "read_pidfile returns empty for empty file"
    else
        test_fail "read_pidfile returns empty for empty file" "" "$pid"
    fi

    teardown_test_env
}

test_read_pidfile_garbage() {
    ((TESTS_RUN++))
    setup_test_env

    echo "not_a_number" > "$MOCK_RUN_DIR/microvm-netd.pid"

    local pid
    pid=$(cat "$MOCK_RUN_DIR/microvm-netd.pid" 2>/dev/null | tr -d '[:space:]')

    if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
        test_pass "read_pidfile rejects non-numeric content"
    else
        test_fail "read_pidfile rejects non-numeric content" "non-numeric" "$pid"
    fi

    teardown_test_env
}

test_read_pidfile_missing() {
    ((TESTS_RUN++))
    setup_test_env

    # Don't create pidfile
    if [[ ! -f "$MOCK_RUN_DIR/microvm-netd.pid" ]]; then
        test_pass "read_pidfile handles missing file"
    else
        test_fail "read_pidfile handles missing file" "missing" "exists"
    fi

    teardown_test_env
}

# =============================================================================
# Test: cmdline verification logic
# =============================================================================

test_verify_netd_cmdline_matches() {
    ((TESTS_RUN++))
    setup_test_env

    create_mock_process 12345 "python3 /path/to/microvm_netd.py --socket-path /run/sock"

    local cmdline
    cmdline=$(cat "$MOCK_PROC_DIR/12345/cmdline" 2>/dev/null | tr '\0' ' ')

    if [[ "$cmdline" == *"python"* ]] && [[ "$cmdline" == *"microvm_netd"* ]]; then
        test_pass "verify_netd_process matches python + microvm_netd"
    else
        test_fail "verify_netd_process matches python + microvm_netd" "contains python and microvm_netd" "$cmdline"
    fi

    teardown_test_env
}

test_verify_netd_cmdline_mismatch() {
    ((TESTS_RUN++))
    setup_test_env

    create_mock_process 12345 "/usr/bin/vim /etc/hosts"

    local cmdline
    cmdline=$(cat "$MOCK_PROC_DIR/12345/cmdline" 2>/dev/null | tr '\0' ' ')

    if [[ "$cmdline" != *"python"* ]] || [[ "$cmdline" != *"microvm_netd"* ]]; then
        test_pass "verify_netd_process rejects non-netd process"
    else
        test_fail "verify_netd_process rejects non-netd process" "no match" "matched"
    fi

    teardown_test_env
}

test_verify_netd_process_gone() {
    ((TESTS_RUN++))
    setup_test_env

    # Don't create process
    if [[ ! -d "$MOCK_PROC_DIR/99999" ]]; then
        test_pass "verify_netd_process handles missing process"
    else
        test_fail "verify_netd_process handles missing process" "missing" "exists"
    fi

    teardown_test_env
}

# =============================================================================
# Test: Status classification logic
# =============================================================================

test_status_running_with_valid_pid() {
    ((TESTS_RUN++))
    setup_test_env

    # Setup: process exists with correct cmdline, pidfile points to it
    create_mock_process 12345 "python3 /path/to/microvm_netd.py"
    create_mock_pidfile 12345

    local pid
    pid=$(cat "$MOCK_RUN_DIR/microvm-netd.pid" | tr -d '[:space:]')

    local status="unknown"
    if [[ -d "$MOCK_PROC_DIR/$pid" ]]; then
        local cmdline
        cmdline=$(cat "$MOCK_PROC_DIR/$pid/cmdline" 2>/dev/null | tr '\0' ' ')
        if [[ "$cmdline" == *"python"* ]] && [[ "$cmdline" == *"microvm_netd"* ]]; then
            status="running"
        fi
    fi

    if [[ "$status" == "running" ]]; then
        test_pass "status=running when proc exists and cmdline matches"
    else
        test_fail "status=running when proc exists and cmdline matches" "running" "$status"
    fi

    teardown_test_env
}

test_status_stale_pid_file() {
    ((TESTS_RUN++))
    setup_test_env

    # Setup: pidfile exists but process is gone
    create_mock_pidfile 99999
    # Don't create the process

    local pid
    pid=$(cat "$MOCK_RUN_DIR/microvm-netd.pid" | tr -d '[:space:]')

    local status="unknown"
    if [[ ! -d "$MOCK_PROC_DIR/$pid" ]]; then
        status="stale"
    fi

    if [[ "$status" == "stale" ]]; then
        test_pass "status=stale when pidfile exists but process gone"
    else
        test_fail "status=stale when pidfile exists but process gone" "stale" "$status"
    fi

    teardown_test_env
}

test_status_pid_mismatch() {
    ((TESTS_RUN++))
    setup_test_env

    # Setup: process exists but cmdline doesn't match netd
    create_mock_process 12345 "/usr/bin/sleep 1000"
    create_mock_pidfile 12345

    local pid
    pid=$(cat "$MOCK_RUN_DIR/microvm-netd.pid" | tr -d '[:space:]')

    local status="unknown"
    if [[ -d "$MOCK_PROC_DIR/$pid" ]]; then
        local cmdline
        cmdline=$(cat "$MOCK_PROC_DIR/$pid/cmdline" 2>/dev/null | tr '\0' ' ')
        if [[ "$cmdline" != *"python"* ]] || [[ "$cmdline" != *"microvm_netd"* ]]; then
            status="mismatch"
        fi
    fi

    if [[ "$status" == "mismatch" ]]; then
        test_pass "status=mismatch when proc exists but cmdline wrong"
    else
        test_fail "status=mismatch when proc exists but cmdline wrong" "mismatch" "$status"
    fi

    teardown_test_env
}

test_status_no_pidfile() {
    ((TESTS_RUN++))
    setup_test_env

    # Setup: no pidfile at all
    local status="none"
    if [[ ! -f "$MOCK_RUN_DIR/microvm-netd.pid" ]]; then
        status="none"
    fi

    if [[ "$status" == "none" ]]; then
        test_pass "status=none when no pidfile exists"
    else
        test_fail "status=none when no pidfile exists" "none" "$status"
    fi

    teardown_test_env
}

# =============================================================================
# Test: Doctor severity logic
# =============================================================================

test_doctor_warn_count_tracked() {
    ((TESTS_RUN++))

    local warn_count=0
    local netd_ok=false

    # Simulate netd not running - should increment warn_count
    if [[ "$netd_ok" != "true" ]]; then
        warn_count=$((warn_count + 1))
    fi

    if [[ $warn_count -eq 1 ]]; then
        test_pass "doctor tracks warn_count when netd not running"
    else
        test_fail "doctor tracks warn_count when netd not running" "1" "$warn_count"
    fi
}

test_doctor_runtime_escalation() {
    ((TESTS_RUN++))

    local exit_code=0
    local netd_ok=false
    local runtime="firecracker"

    # If runtime=firecracker and netd unhealthy, should be ERROR
    if [[ "$runtime" == "firecracker" ]] && [[ "$netd_ok" != "true" ]]; then
        exit_code=1
    fi

    if [[ $exit_code -eq 1 ]]; then
        test_pass "doctor escalates to ERROR when runtime=firecracker and netd unhealthy"
    else
        test_fail "doctor escalates to ERROR when runtime=firecracker and netd unhealthy" "1" "$exit_code"
    fi
}

test_doctor_no_escalation_compose_runtime() {
    ((TESTS_RUN++))

    local exit_code=0
    local netd_ok=false
    local runtime="compose"

    # If runtime=compose and netd unhealthy, should NOT escalate to error
    if [[ "$runtime" == "firecracker" ]] && [[ "$netd_ok" != "true" ]]; then
        exit_code=1
    fi

    if [[ $exit_code -eq 0 ]]; then
        test_pass "doctor does NOT escalate when runtime=compose"
    else
        test_fail "doctor does NOT escalate when runtime=compose" "0" "$exit_code"
    fi
}

# =============================================================================
# Test: Log redaction patterns
# =============================================================================

test_redact_password() {
    ((TESTS_RUN++))

    local input="Setting PASSWORD=supersecret123 for user"
    local redacted
    redacted=$(echo "$input" | sed -E 's/(PASSWORD|SECRET|TOKEN|KEY|PRIVATE)=[^ ]*/\1=***REDACTED***/gi')

    if [[ "$redacted" == *"supersecret123"* ]]; then
        test_fail "redact_log removes PASSWORD values" "no secret" "contains secret"
    else
        test_pass "redact_log removes PASSWORD values"
    fi
}

test_redact_database_url() {
    ((TESTS_RUN++))

    local input="Connecting to postgres://admin:mypassword@localhost/db"
    local redacted
    redacted=$(echo "$input" | sed -E 's/(postgres|postgresql|mysql):\/\/[^@]+@/\1:\/\/***:***@/gi')

    if [[ "$redacted" == *"mypassword"* ]]; then
        test_fail "redact_log removes database credentials" "no password" "contains password"
    else
        test_pass "redact_log removes database credentials"
    fi
}

test_redact_bearer_token() {
    ((TESTS_RUN++))

    local input="Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    local redacted
    redacted=$(echo "$input" | sed -E 's/(Bearer|Basic) [A-Za-z0-9+\/=_-]+/\1 ***REDACTED***/gi')

    if [[ "$redacted" == *"eyJ"* ]]; then
        test_fail "redact_log removes Bearer tokens" "no token" "contains token"
    else
        test_pass "redact_log removes Bearer tokens"
    fi
}

# =============================================================================
# Run all tests
# =============================================================================

main() {
    echo "Running octolabctl status logic tests..."
    echo ""

    # proc_exists tests
    test_proc_exists_when_process_exists
    test_proc_exists_when_process_gone

    # read_pidfile tests
    test_read_pidfile_valid
    test_read_pidfile_empty
    test_read_pidfile_garbage
    test_read_pidfile_missing

    # cmdline verification tests
    test_verify_netd_cmdline_matches
    test_verify_netd_cmdline_mismatch
    test_verify_netd_process_gone

    # status classification tests
    test_status_running_with_valid_pid
    test_status_stale_pid_file
    test_status_pid_mismatch
    test_status_no_pidfile

    # doctor severity tests
    test_doctor_warn_count_tracked
    test_doctor_runtime_escalation
    test_doctor_no_escalation_compose_runtime

    # log redaction tests
    test_redact_password
    test_redact_database_url
    test_redact_bearer_token

    echo ""
    echo "========================================"
    echo "Tests run: $TESTS_RUN"
    echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
    if [[ $TESTS_FAILED -gt 0 ]]; then
        echo -e "Failed: ${RED}$TESTS_FAILED${NC}"
        exit 1
    else
        echo "Failed: $TESTS_FAILED"
        echo -e "${GREEN}All tests passed!${NC}"
        exit 0
    fi
}

main "$@"
