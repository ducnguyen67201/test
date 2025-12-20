#!/usr/bin/env python3
"""Snapshot current system state for debugging and rollback.

Captures:
- Git status and diff
- Docker containers, networks, volumes
- Guacamole stack status and logs
- HTTP health checks
- Pytest summary (non-fatal: records pre-existing test failures)

All outputs are redacted to remove secrets.
Uses subprocess.run with shell=False for security.

Usage:
    python3 dev/scripts/snapshot_state.py
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Project paths
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
SNAPSHOTS_DIR = BACKEND_DIR / "var" / "snapshots"
GUAC_COMPOSE = REPO_ROOT / "infra" / "guacamole" / "docker-compose.yml"

# Patterns for secrets to redact
SECRET_PATTERNS = [
    r"(PASS|PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL|AUTH)(\s*[:=]\s*)([^\s\n\"']+)",
    r"(password|secret|token|key|credential)(\s*[:=]\s*)([^\s\n\"']+)",
    r"postgresql://[^:]+:([^@]+)@",  # DB password in URL
    r"postgres://[^:]+:([^@]+)@",
    r"Bearer\s+([A-Za-z0-9\-._~+/]+=*)",  # Bearer tokens
]


def redact_secrets(text: str) -> str:
    """Redact sensitive values from text.

    Args:
        text: Input text that may contain secrets

    Returns:
        Text with secrets replaced by [REDACTED]
    """
    if not text:
        return text

    result = text

    # Redact KEY=VALUE patterns for sensitive keys
    result = re.sub(
        r"(PASS|PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL|AUTH|ENC_KEY)(\s*[:=]\s*)([^\s\n\"']+)",
        r"\1\2[REDACTED]",
        result,
        flags=re.IGNORECASE,
    )

    # Redact passwords in database URLs
    result = re.sub(
        r"(postgresql://[^:]+:)([^@]+)(@)",
        r"\1[REDACTED]\3",
        result,
    )
    result = re.sub(
        r"(postgres://[^:]+:)([^@]+)(@)",
        r"\1[REDACTED]\3",
        result,
    )

    # Redact Bearer tokens
    result = re.sub(
        r"(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)",
        r"\1[REDACTED]",
        result,
    )

    return result


def run_command(
    cmd: list[str],
    timeout: float = 30.0,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Run a command and capture output.

    Args:
        cmd: Command as list of strings
        timeout: Timeout in seconds
        cwd: Working directory

    Returns:
        Dict with returncode, stdout, stderr (all redacted)
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            shell=False,  # SECURITY: Never use shell=True
        )
        return {
            "returncode": result.returncode,
            "stdout": redact_secrets(result.stdout),
            "stderr": redact_secrets(result.stderr),
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except FileNotFoundError:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": f"Command not found: {cmd[0]}",
        }
    except Exception as e:
        return {
            "returncode": -3,
            "stdout": "",
            "stderr": f"Error: {type(e).__name__}",
        }


def http_check(url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Check HTTP endpoint status.

    Args:
        url: URL to check
        timeout: Timeout in seconds

    Returns:
        Dict with status_code and body_preview (redacted)
    """
    result = run_command(
        ["curl", "-s", "-o", "-", "-w", "\n%{http_code}", url],
        timeout=timeout,
    )

    if result["returncode"] != 0:
        return {
            "reachable": False,
            "error": result["stderr"] or "curl failed",
        }

    lines = result["stdout"].strip().split("\n")
    if lines:
        status_code = lines[-1] if lines[-1].isdigit() else "0"
        body = "\n".join(lines[:-1])[:500]  # First 500 chars
        return {
            "reachable": True,
            "status_code": int(status_code),
            "body_preview": redact_secrets(body),
        }

    return {"reachable": False, "error": "Empty response"}


def collect_git_state() -> dict[str, Any]:
    """Collect git repository state."""
    return {
        "head": run_command(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT),
        "branch": run_command(["git", "branch", "--show-current"], cwd=REPO_ROOT),
        "status": run_command(["git", "status", "--porcelain"], cwd=REPO_ROOT),
        "diff_stat": run_command(["git", "diff", "--stat"], cwd=REPO_ROOT),
    }


def collect_docker_state() -> dict[str, Any]:
    """Collect Docker containers, networks, volumes state."""
    return {
        "containers": run_command(
            ["docker", "ps", "-a", "--format",
             "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
        ),
        "networks": run_command(["docker", "network", "ls"]),
        "volumes": run_command(["docker", "volume", "ls"]),
    }


def collect_guac_state() -> dict[str, Any]:
    """Collect Guacamole stack state."""
    if not GUAC_COMPOSE.exists():
        return {"error": f"Compose file not found: {GUAC_COMPOSE}"}

    compose_cmd = ["docker", "compose", "-f", str(GUAC_COMPOSE)]

    return {
        "ps": run_command([*compose_cmd, "ps"]),
        "logs_guacamole": run_command(
            [*compose_cmd, "logs", "--tail=100", "guacamole"],
            timeout=15.0,
        ),
        "logs_guacd": run_command(
            [*compose_cmd, "logs", "--tail=100", "guacd"],
            timeout=15.0,
        ),
        "logs_db": run_command(
            [*compose_cmd, "logs", "--tail=50", "guac-db"],
            timeout=15.0,
        ),
    }


def collect_health_checks() -> dict[str, Any]:
    """Collect HTTP health check results."""
    return {
        "guac_ui": http_check("http://127.0.0.1:8081/guacamole/"),
        "backend_health": http_check("http://127.0.0.1:8000/health"),
        "backend_root": http_check("http://127.0.0.1:8000/"),
    }


def collect_openapi_routes() -> dict[str, Any]:
    """Collect OpenAPI routes from backend with methods.

    Returns:
        Dict with:
        - openapi_paths: {path: [methods]}
        - auth_matrix: {register, login, me} endpoints
        - route_count: total number of routes
        - auth_routes: list of auth-related paths
    """
    result = run_command(
        ["curl", "-s", "http://127.0.0.1:8000/openapi.json"],
        timeout=10.0,
    )

    if result["returncode"] != 0:
        return {"error": result["stderr"] or "curl failed", "openapi_paths": {}}

    try:
        openapi = json.loads(result["stdout"])
        raw_paths = openapi.get("paths", {})

        # Build paths with methods
        openapi_paths = {}
        for path, methods_data in raw_paths.items():
            methods = [
                m.upper() for m in methods_data.keys()
                if m.lower() not in ("parameters", "summary", "description")
            ]
            openapi_paths[path] = methods

        paths = sorted(openapi_paths.keys())

        # Filter auth-related routes
        auth_routes = [p for p in paths if any(
            kw in p.lower() for kw in ["auth", "register", "signup", "login", "user"]
        )]

        # Build auth matrix
        register_path = None
        login_path = None
        me_path = None

        for path in paths:
            path_lower = path.lower()
            if "register" in path_lower and "auth" in path_lower:
                register_path = path
            if "login" in path_lower and "auth" in path_lower:
                login_path = path
            if path_lower in ("/auth/me", "/auth/me/"):
                me_path = path

        auth_matrix = {
            "register": {
                "path": register_path,
                "methods": openapi_paths.get(register_path, []) if register_path else [],
            },
            "login": {
                "path": login_path,
                "methods": openapi_paths.get(login_path, []) if login_path else [],
            },
            "me": {
                "path": me_path,
                "methods": openapi_paths.get(me_path, []) if me_path else [],
            },
        }

        return {
            "openapi_paths": openapi_paths,
            "auth_matrix": auth_matrix,
            "all_routes": paths,
            "auth_routes": auth_routes,
            "route_count": len(paths),
        }
    except json.JSONDecodeError:
        return {"error": "Invalid JSON response", "openapi_paths": {}}


def collect_register_grep() -> dict[str, Any]:
    """Search for register/signup patterns in codebase.

    Returns:
        Dict with grep results for backend and frontend
    """
    backend_result = run_command(
        ["grep", "-rn", "-E", "register|signup", "backend/app"],
        timeout=15.0,
        cwd=REPO_ROOT,
    )
    frontend_result = run_command(
        ["grep", "-rn", "-E", "register|signup", "frontend/src"],
        timeout=15.0,
        cwd=REPO_ROOT,
    )

    return {
        "backend": {
            "found": backend_result["returncode"] == 0,
            "lines": backend_result["stdout"].strip().split("\n") if backend_result["stdout"].strip() else [],
        },
        "frontend": {
            "found": frontend_result["returncode"] == 0,
            "lines": frontend_result["stdout"].strip().split("\n") if frontend_result["stdout"].strip() else [],
        },
    }


def collect_evidence_state() -> dict[str, Any]:
    """Collect evidence-related state.

    Returns:
        Dict with:
        - api_endpoints: Evidence API endpoint status
        - volumes: Evidence-related Docker volumes
        - frontend_button: Whether frontend has download button
    """
    # Check evidence endpoints in OpenAPI
    openapi_result = run_command(
        ["curl", "-s", "http://127.0.0.1:8000/openapi.json"],
        timeout=10.0,
    )

    evidence_endpoints = {}
    if openapi_result["returncode"] == 0:
        try:
            openapi = json.loads(openapi_result["stdout"])
            paths = openapi.get("paths", {})
            for path, methods in paths.items():
                if "evidence" in path.lower():
                    evidence_endpoints[path] = list(
                        m.upper() for m in methods.keys()
                        if m.lower() not in ("parameters", "summary", "description")
                    )
        except json.JSONDecodeError:
            pass

    # Check for evidence-related volumes
    volumes_result = run_command(["docker", "volume", "ls", "--format", "{{.Name}}"])
    volume_names = volumes_result.get("stdout", "").strip().split("\n") if volumes_result.get("stdout") else []

    evidence_volumes = [v for v in volume_names if any(
        kw in v.lower() for kw in ["evidence", "pcap"]
    )]

    # Check frontend for evidence download
    frontend_result = run_command(
        ["grep", "-rn", "-E", "evidence|downloadLabEvidence", "frontend/src"],
        timeout=15.0,
        cwd=REPO_ROOT,
    )
    has_frontend_button = "downloadLabEvidence" in frontend_result.get("stdout", "")

    return {
        "api_endpoints": evidence_endpoints,
        "endpoint_count": len(evidence_endpoints),
        "volumes": evidence_volumes,
        "volume_count": len(evidence_volumes),
        "frontend_button": has_frontend_button,
    }


def collect_pytest_summary() -> dict[str, Any]:
    """Run pytest and capture summary (non-fatal).

    This captures pre-existing test failures honestly.
    The snapshot continues even if tests fail.

    Returns:
        Dict with exit_code, summary_lines (last 200 lines), and passed/failed counts
    """
    # Check if backend/tests exists
    tests_dir = BACKEND_DIR / "tests"
    if not tests_dir.exists():
        return {
            "skipped": True,
            "reason": "tests directory not found",
        }

    # Run pytest with quiet mode, capture output
    # Use longer timeout since tests can take a while
    result = run_command(
        ["python3", "-m", "pytest", "-q", "--tb=short", "tests/"],
        timeout=120.0,
        cwd=BACKEND_DIR,
    )

    # Parse the output
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    exit_code = result.get("returncode", -1)

    # Get last 200 lines of output
    output_lines = stdout.split("\n")
    summary_lines = output_lines[-200:] if len(output_lines) > 200 else output_lines

    # Try to extract pass/fail counts from pytest output
    # pytest summary line looks like: "5 passed, 2 failed, 1 skipped in 1.23s"
    passed = 0
    failed = 0
    skipped = 0
    errors = 0

    for line in reversed(output_lines):
        # Look for the summary line
        if "passed" in line or "failed" in line or "error" in line:
            import re as regex
            match = regex.search(r"(\d+) passed", line)
            if match:
                passed = int(match.group(1))
            match = regex.search(r"(\d+) failed", line)
            if match:
                failed = int(match.group(1))
            match = regex.search(r"(\d+) skipped", line)
            if match:
                skipped = int(match.group(1))
            match = regex.search(r"(\d+) error", line)
            if match:
                errors = int(match.group(1))
            if passed or failed or skipped or errors:
                break

    return {
        "exit_code": exit_code,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "summary_lines": summary_lines,
        "stderr_preview": stderr[:500] if stderr else "",
    }


def create_snapshot() -> Path:
    """Create a snapshot of current state.

    Returns:
        Path to snapshot directory
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = SNAPSHOTS_DIR / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    print(f"Creating snapshot at: {snapshot_dir}")

    # Collect all state
    print("  Collecting git state...")
    git_state = collect_git_state()
    print("  Collecting docker state...")
    docker_state = collect_docker_state()
    print("  Collecting guacamole state...")
    guac_state = collect_guac_state()
    print("  Collecting health checks...")
    health_state = collect_health_checks()
    print("  Collecting OpenAPI routes...")
    openapi_state = collect_openapi_routes()
    print("  Collecting register/signup grep...")
    register_grep_state = collect_register_grep()
    print("  Collecting evidence state...")
    evidence_state = collect_evidence_state()
    print("  Running pytest (this may take a while)...")
    pytest_state = collect_pytest_summary()

    snapshot = {
        "timestamp": timestamp,
        "git": git_state,
        "docker": docker_state,
        "guacamole": guac_state,
        "health": health_state,
        "openapi": openapi_state,
        "register_grep": register_grep_state,
        "evidence": evidence_state,
        "pytest": pytest_state,
    }

    # Write main snapshot JSON
    snapshot_file = snapshot_dir / "snapshot.json"
    with open(snapshot_file, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    print(f"  Wrote: {snapshot_file}")

    # Write git diff to separate file if there are changes
    git_status = snapshot["git"]["status"]
    if git_status.get("stdout", "").strip():
        diff_result = run_command(["git", "diff"], cwd=REPO_ROOT)
        diff_file = snapshot_dir / "git_diff.patch"
        with open(diff_file, "w") as f:
            f.write(diff_result.get("stdout", ""))
        print(f"  Wrote: {diff_file}")

    # Write pytest output to separate file
    pytest_data = snapshot["pytest"]
    if not pytest_data.get("skipped"):
        pytest_file = snapshot_dir / "pytest_output.txt"
        with open(pytest_file, "w") as f:
            f.write(f"Exit code: {pytest_data.get('exit_code', -1)}\n")
            f.write(f"Passed: {pytest_data.get('passed', 0)}\n")
            f.write(f"Failed: {pytest_data.get('failed', 0)}\n")
            f.write(f"Errors: {pytest_data.get('errors', 0)}\n")
            f.write(f"Skipped: {pytest_data.get('skipped', 0)}\n")
            f.write("\n--- Output (last 200 lines) ---\n\n")
            f.write("\n".join(pytest_data.get("summary_lines", [])))
            if pytest_data.get("stderr_preview"):
                f.write("\n\n--- Stderr ---\n\n")
                f.write(pytest_data.get("stderr_preview", ""))
        print(f"  Wrote: {pytest_file}")

    # Summary
    print("\n=== Snapshot Summary ===")

    # Git
    head = snapshot["git"]["head"].get("stdout", "").strip()[:12]
    branch = snapshot["git"]["branch"].get("stdout", "").strip()
    status_lines = len(snapshot["git"]["status"].get("stdout", "").strip().split("\n"))
    if snapshot["git"]["status"].get("stdout", "").strip():
        print(f"Git: {branch} @ {head} ({status_lines} uncommitted changes)")
    else:
        print(f"Git: {branch} @ {head} (clean)")

    # Health checks
    guac_status = snapshot["health"]["guac_ui"]
    backend_status = snapshot["health"]["backend_health"]

    if guac_status.get("reachable"):
        print(f"Guac UI: HTTP {guac_status.get('status_code')}")
    else:
        print(f"Guac UI: UNREACHABLE ({guac_status.get('error', 'unknown')})")

    if backend_status.get("reachable"):
        print(f"Backend: HTTP {backend_status.get('status_code')}")
    else:
        # Try root endpoint
        root_status = snapshot["health"]["backend_root"]
        if root_status.get("reachable"):
            print(f"Backend: HTTP {root_status.get('status_code')} (root endpoint)")
        else:
            print(f"Backend: UNREACHABLE ({backend_status.get('error', 'unknown')})")

    # OpenAPI routes summary
    openapi_data = snapshot.get("openapi", {})
    if openapi_data.get("error"):
        print(f"OpenAPI: ERROR ({openapi_data.get('error')})")
    else:
        route_count = openapi_data.get("route_count", 0)
        auth_matrix = openapi_data.get("auth_matrix", {})
        print(f"OpenAPI: {route_count} routes")

        # Show auth matrix
        for key in ["register", "login", "me"]:
            entry = auth_matrix.get(key, {})
            path = entry.get("path", "not found")
            methods = entry.get("methods", [])
            methods_str = ",".join(methods) if methods else "none"
            print(f"  {key}: {path} [{methods_str}]")

    # Register grep summary
    grep_data = snapshot.get("register_grep", {})
    backend_grep = grep_data.get("backend", {})
    frontend_grep = grep_data.get("frontend", {})
    backend_count = len(backend_grep.get("lines", []))
    frontend_count = len(frontend_grep.get("lines", []))
    print(f"Register grep: backend={backend_count} lines, frontend={frontend_count} lines")

    # Evidence summary
    evidence_data = snapshot.get("evidence", {})
    evidence_endpoints = evidence_data.get("api_endpoints", {})
    evidence_volumes = evidence_data.get("volumes", [])
    has_frontend_btn = evidence_data.get("frontend_button", False)
    print(f"Evidence: {len(evidence_endpoints)} API endpoints, {len(evidence_volumes)} volumes, frontend_button={has_frontend_btn}")
    for path, methods in evidence_endpoints.items():
        print(f"  {path} [{','.join(methods)}]")

    # Pytest summary
    pytest_data = snapshot["pytest"]
    if pytest_data.get("skipped"):
        print(f"Pytest: SKIPPED ({pytest_data.get('reason', 'unknown')})")
    else:
        exit_code = pytest_data.get("exit_code", -1)
        passed = pytest_data.get("passed", 0)
        failed = pytest_data.get("failed", 0)
        skipped = pytest_data.get("skipped", 0)
        errors = pytest_data.get("errors", 0)

        if exit_code == 0:
            print(f"Pytest: PASSED ({passed} passed, {skipped} skipped)")
        else:
            print(f"Pytest: FAILED (exit={exit_code}) - {passed} passed, {failed} failed, {errors} errors, {skipped} skipped")

    return snapshot_dir


def maybe_create_branch() -> bool:
    """Create a snapshot branch if there are uncommitted changes.

    Returns:
        True if branch was created
    """
    status_result = run_command(["git", "status", "--porcelain"], cwd=REPO_ROOT)
    has_changes = bool(status_result.get("stdout", "").strip())

    if not has_changes:
        print("No uncommitted changes - skipping branch creation")
        return False

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    branch_name = f"snapshot/{timestamp}-working"

    # Check if branch already exists
    check_result = run_command(
        ["git", "show-ref", "--verify", f"refs/heads/{branch_name}"],
        cwd=REPO_ROOT,
    )
    if check_result["returncode"] == 0:
        print(f"Branch {branch_name} already exists")
        return False

    # Create branch
    result = run_command(
        ["git", "checkout", "-b", branch_name],
        cwd=REPO_ROOT,
    )
    if result["returncode"] != 0:
        print(f"Failed to create branch: {result['stderr']}")
        return False

    # Commit
    run_command(["git", "add", "-A"], cwd=REPO_ROOT)
    result = run_command(
        ["git", "commit", "-m", "snapshot: working guac+octobox before evidence isolation"],
        cwd=REPO_ROOT,
    )
    if result["returncode"] != 0:
        print(f"Failed to commit: {result['stderr']}")
        return False

    print(f"Created snapshot branch: {branch_name}")
    return True


def main():
    """Main entry point."""
    print("=" * 60)
    print("OctoLab State Snapshot")
    print("=" * 60)
    print()

    # Create snapshot
    snapshot_dir = create_snapshot()

    print()
    print(f"Snapshot saved to: {snapshot_dir}")
    print()

    # Optionally create branch
    # Commented out by default - uncomment to auto-create branches
    # maybe_create_branch()

    return 0


if __name__ == "__main__":
    sys.exit(main())
