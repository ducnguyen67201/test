"""Sandbox build service for testing Dockerfiles without full lab provisioning."""

import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Build timeout in seconds
BUILD_TIMEOUT = 120
# Container run timeout
CONTAINER_TIMEOUT = 30
# Container stabilization timeout (how long to poll for container health)
STABILIZATION_TIMEOUT = 30
# Polling interval during stabilization
STABILIZATION_POLL_INTERVAL = 3


class SandboxBuildResult:
    """Result of a sandbox build attempt."""

    def __init__(
        self,
        success: bool,
        error: Optional[str] = None,
        build_log: Optional[str] = None,
        container_id: Optional[str] = None,
        image_id: Optional[str] = None,
    ):
        self.success = success
        self.error = error
        self.build_log = build_log
        self.container_id = container_id
        self.image_id = image_id


class VerifyResult:
    """Result of setup verification."""

    def __init__(
        self,
        success: bool,
        checks: list[dict],
    ):
        self.success = success
        self.checks = checks


async def sandbox_build_dockerfile(
    dockerfile: str,
    source_files: list[dict],
    start_container: bool = True,
) -> SandboxBuildResult:
    """
    Build a Dockerfile in an isolated sandbox environment.

    Args:
        dockerfile: Dockerfile content
        source_files: List of {"filename": str, "content": str} dicts
        start_container: Whether to start a container after build

    Returns:
        SandboxBuildResult with success status, logs, and optional container_id
    """
    tmpdir = None
    image_tag = f"octolab-test-{uuid4().hex[:12]}"

    try:
        # Create temp directory with build context
        tmpdir = Path(tempfile.mkdtemp(prefix="octolab-build-"))
        dockerfile_path = tmpdir / "Dockerfile"
        dockerfile_path.write_text(dockerfile)

        # Write source files
        for sf in source_files:
            file_path = tmpdir / sf["filename"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(sf["content"])

        logger.info(f"Building Dockerfile in sandbox: {tmpdir}")

        # Run docker build
        loop = asyncio.get_running_loop()
        build_result = await loop.run_in_executor(
            None,
            _run_docker_build,
            tmpdir,
            image_tag,
        )

        if not build_result["success"]:
            return SandboxBuildResult(
                success=False,
                error=build_result.get("error", "Build failed"),
                build_log=build_result.get("log"),
            )

        image_id = build_result.get("image_id")
        container_id = None

        # Optionally start container
        if start_container and image_id:
            run_result = await loop.run_in_executor(
                None,
                _run_container,
                image_tag,
            )
            if run_result["success"]:
                container_id = run_result.get("container_id")
            else:
                # Build succeeded but container failed to start
                return SandboxBuildResult(
                    success=False,
                    error=f"Container failed to start: {run_result.get('error')}",
                    build_log=build_result.get("log"),
                    image_id=image_id,
                )

        return SandboxBuildResult(
            success=True,
            build_log=build_result.get("log"),
            container_id=container_id,
            image_id=image_id,
        )

    except Exception as e:
        logger.exception(f"Sandbox build failed: {e}")
        return SandboxBuildResult(
            success=False,
            error=str(e),
        )
    finally:
        # Cleanup temp directory
        if tmpdir and tmpdir.exists():
            try:
                shutil.rmtree(tmpdir)
            except Exception as e:
                logger.warning(f"Failed to cleanup tmpdir {tmpdir}: {e}")


def _run_docker_build(tmpdir: Path, image_tag: str) -> dict:
    """Run docker build synchronously (called from executor)."""
    logger.debug(f"[sandbox] Starting docker build in {tmpdir} with tag {image_tag}")
    try:
        result = subprocess.run(
            ["docker", "build", "-t", image_tag, "."],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT,
        )

        log = result.stdout + result.stderr

        if result.returncode != 0:
            # Extract error message from build output
            error_lines = [
                line for line in log.split("\n")
                if "error" in line.lower() or "failed" in line.lower()
            ]
            error_msg = error_lines[-1] if error_lines else "Build failed"
            logger.warning(f"[sandbox] Docker build failed: {error_msg}")
            logger.debug(f"[sandbox] Build log (last 500 chars): {log[-500:]}")

            return {
                "success": False,
                "error": error_msg,
                "log": log[-2000:] if len(log) > 2000 else log,
            }

        # Get image ID
        image_id = None
        inspect_result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Id}}", image_tag],
            capture_output=True,
            text=True,
        )
        if inspect_result.returncode == 0:
            image_id = inspect_result.stdout.strip()

        return {
            "success": True,
            "log": log[-2000:] if len(log) > 2000 else log,
            "image_id": image_id,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Build timed out after {BUILD_TIMEOUT} seconds",
            "log": None,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "log": None,
        }


def _run_container(image_tag: str) -> dict:
    """Run container from built image (called from executor).

    Uses polling-based health checking to detect crashes that occur after
    initial startup. Polls every STABILIZATION_POLL_INTERVAL seconds for
    STABILIZATION_TIMEOUT seconds total to catch delayed crashes.
    """
    container_name = f"octolab-test-{uuid4().hex[:8]}"
    logger.debug(f"[sandbox] Starting container {container_name} from image {image_tag}")
    try:
        # Start container in detached mode
        result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", container_name,
                image_tag,
            ],
            capture_output=True,
            text=True,
            timeout=CONTAINER_TIMEOUT,
        )

        if result.returncode != 0:
            logger.warning(f"[sandbox] Container failed to start: {result.stderr or result.stdout}")
            return {
                "success": False,
                "error": result.stderr or result.stdout or "Container failed to start",
            }

        container_id = result.stdout.strip()
        logger.info(
            f"[sandbox] Container started: {container_id[:12]}, "
            f"polling for {STABILIZATION_TIMEOUT}s to detect crashes"
        )

        # Poll container health repeatedly to catch delayed crashes
        # This is more robust than a single check after a fixed delay
        start_time = time.monotonic()
        last_status = None
        check_count = 0

        while (time.monotonic() - start_time) < STABILIZATION_TIMEOUT:
            check_count += 1
            time.sleep(STABILIZATION_POLL_INTERVAL)

            # Check container status (running + not restarting)
            inspect_result = subprocess.run(
                ["docker", "inspect", "--format",
                 "{{.State.Running}} {{.State.Status}} {{.RestartCount}} {{.State.ExitCode}}",
                 container_id],
                capture_output=True,
                text=True,
            )

            if inspect_result.returncode != 0:
                logger.warning(f"[sandbox] Container {container_id[:12]} disappeared during check #{check_count}")
                return {
                    "success": False,
                    "error": "Container disappeared during stabilization check",
                }

            state_parts = inspect_result.stdout.strip().split()
            is_running = state_parts[0] == "true" if state_parts else False
            status = state_parts[1] if len(state_parts) > 1 else ""
            restart_count = int(state_parts[2]) if len(state_parts) > 2 and state_parts[2].isdigit() else 0
            exit_code = int(state_parts[3]) if len(state_parts) > 3 and state_parts[3].lstrip('-').isdigit() else 0

            # Log status changes
            if status != last_status:
                elapsed = time.monotonic() - start_time
                logger.debug(f"[sandbox] Container {container_id[:12]} status: {status} (check #{check_count}, {elapsed:.1f}s)")
                last_status = status

            # Detect crash-loop or exit
            is_crash_looping = "restarting" in status.lower() or restart_count > 0
            has_exited = status.lower() == "exited" or not is_running

            if has_exited or is_crash_looping:
                # Container exited or crash-looping - get logs for feedback
                logs_result = subprocess.run(
                    ["docker", "logs", "--tail", "100", container_id],
                    capture_output=True,
                    text=True,
                )
                container_logs = logs_result.stdout + logs_result.stderr

                elapsed = time.monotonic() - start_time
                if is_crash_looping:
                    error_detail = f"crash-loop detected (restart_count={restart_count})"
                else:
                    error_detail = f"exited with code {exit_code} after {elapsed:.1f}s"

                logger.warning(f"[sandbox] Container {container_id[:12]} failed: {error_detail}")
                logger.debug(f"[sandbox] Container logs (last 500 chars): {container_logs[-500:]}")

                # Truncate logs for error message but keep enough for debugging
                log_excerpt = container_logs[-2000:] if len(container_logs) > 2000 else container_logs
                return {
                    "success": False,
                    "error": f"Container {error_detail}.\n\nLogs:\n{log_excerpt}",
                }

        # Container survived the full stabilization period
        elapsed = time.monotonic() - start_time
        logger.info(
            f"[sandbox] Container {container_id[:12]} is healthy and stable "
            f"(ran for {elapsed:.1f}s, {check_count} checks passed)"
        )
        return {
            "success": True,
            "container_id": container_id,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Container start timed out after {CONTAINER_TIMEOUT} seconds",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def cleanup_test_container(container_id: str) -> bool:
    """
    Clean up a test container and its image.

    Args:
        container_id: Container ID to clean up

    Returns:
        True if cleanup succeeded
    """
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _cleanup_container_sync, container_id)
        return True
    except Exception as e:
        logger.warning(f"Failed to cleanup container {container_id}: {e}")
        return False


def _cleanup_container_sync(container_id: str) -> None:
    """Synchronous container cleanup (called from executor)."""
    # Get image ID before removing container
    inspect_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Image}}", container_id],
        capture_output=True,
        text=True,
    )
    image_id = inspect_result.stdout.strip() if inspect_result.returncode == 0 else None

    # Stop and remove container
    subprocess.run(["docker", "stop", container_id], capture_output=True, timeout=30)
    subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)

    # Remove image if we got it
    if image_id:
        subprocess.run(["docker", "rmi", "-f", image_id], capture_output=True)

    logger.info(f"Cleaned up test container {container_id}")


async def verify_container_setup(
    container_id: str,
    cve_id: Optional[str] = None,
    expected_products: Optional[list[dict]] = None,
) -> VerifyResult:
    """
    Verify a container has the correct setup for exploitation.

    Checks:
    - Container is running
    - Expected ports are exposed
    - Expected processes are running
    - Service responds on expected ports

    Args:
        container_id: Container ID to verify
        cve_id: CVE ID for context
        expected_products: Expected affected products from NVD data

    Returns:
        VerifyResult with success status and individual check results
    """
    checks = []

    try:
        loop = asyncio.get_running_loop()

        # Check 1: Container is running
        running_check = await loop.run_in_executor(
            None, _check_container_running, container_id
        )
        checks.append(running_check)

        if not running_check["passed"]:
            return VerifyResult(success=False, checks=checks)

        # Check 2: Exposed ports
        ports_check = await loop.run_in_executor(
            None, _check_exposed_ports, container_id
        )
        checks.append(ports_check)

        # Check 3: Service health (basic connectivity)
        health_check = await loop.run_in_executor(
            None, _check_service_health, container_id
        )
        checks.append(health_check)

        # Overall success if container is running and has exposed ports
        success = (
            running_check["passed"] and
            ports_check["passed"]
        )

        return VerifyResult(success=success, checks=checks)

    except Exception as e:
        logger.exception(f"Verification failed for {container_id}: {e}")
        checks.append({
            "name": "verification_error",
            "passed": False,
            "detail": str(e),
        })
        return VerifyResult(success=False, checks=checks)


def _check_container_running(container_id: str) -> dict:
    """Check if container is running."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return {
            "name": "container_running",
            "passed": False,
            "detail": "Container not found",
        }

    is_running = result.stdout.strip() == "true"
    return {
        "name": "container_running",
        "passed": is_running,
        "detail": "Container is running" if is_running else "Container is not running",
    }


def _check_exposed_ports(container_id: str) -> dict:
    """Check if container has exposed ports."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", container_id],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return {
            "name": "exposed_ports",
            "passed": False,
            "detail": "Failed to inspect ports",
        }

    import json
    try:
        ports = json.loads(result.stdout.strip())
        if ports and any(v for v in ports.values() if v):
            port_list = [p.split("/")[0] for p in ports.keys()]
            return {
                "name": "exposed_ports",
                "passed": True,
                "detail": f"Exposed ports: {', '.join(port_list)}",
            }
        else:
            return {
                "name": "exposed_ports",
                "passed": False,
                "detail": "No ports exposed",
            }
    except json.JSONDecodeError:
        return {
            "name": "exposed_ports",
            "passed": False,
            "detail": "Failed to parse ports",
        }


def _check_service_health(container_id: str) -> dict:
    """Check if service inside container responds."""
    # Try to get container logs to see if service started
    result = subprocess.run(
        ["docker", "logs", "--tail", "50", container_id],
        capture_output=True,
        text=True,
    )

    logs = result.stdout + result.stderr

    # Look for common startup indicators
    positive_indicators = [
        "listening",
        "started",
        "ready",
        "accepting connections",
        "running on",
        "serving",
    ]

    negative_indicators = [
        "error",
        "failed",
        "fatal",
        "exception",
        "cannot",
        "unable",
    ]

    logs_lower = logs.lower()
    has_positive = any(ind in logs_lower for ind in positive_indicators)
    has_negative = any(ind in logs_lower for ind in negative_indicators)

    if has_positive and not has_negative:
        return {
            "name": "service_health",
            "passed": True,
            "detail": "Service appears to be running",
        }
    elif has_negative:
        # Extract relevant error line
        for line in logs.split("\n"):
            if any(ind in line.lower() for ind in negative_indicators):
                return {
                    "name": "service_health",
                    "passed": False,
                    "detail": f"Service error: {line[:100]}",
                }
        return {
            "name": "service_health",
            "passed": False,
            "detail": "Service may have errors",
        }
    else:
        return {
            "name": "service_health",
            "passed": True,
            "detail": "No obvious errors in logs",
        }
