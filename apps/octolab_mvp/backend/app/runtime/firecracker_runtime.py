"""Firecracker microVM runtime for OctoLab.

This runtime provides per-lab kernel isolation using Firecracker microVMs.
It implements the LabRuntime protocol for seamless integration with existing flows.

The "layered" approach:
1. Boot a Firecracker microVM with its own kernel
2. Inside the VM, run Docker to start the same compose stack (octobox/target/gateway)
3. Expose OctoBox UI to host via port forwarding (host -> guest:6080)

SECURITY:
- Each lab runs in a separate VM with its own kernel.
- Root inside VM cannot escape to host (assuming no hypervisor bugs).
- All paths derived from server-owned lab_id.
- NO FALLBACK to compose on any failure.
- Fails closed on any security uncertainty.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import tarfile
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.lab import Lab
from app.models.recipe import Recipe
from app.services.firecracker_doctor import run_doctor
from app.services.firecracker_manager import (
    AgentResponse,
    NetworkConfig,
    PreflightResult,
    StaleRootfsError,
    VMMetadata,
    cleanup_network_for_lab,
    cleanup_port_forward_for_lab,
    create_vm,
    destroy_vm,
    preflight,
    send_agent_command,
    setup_network_for_lab,
    setup_port_forward_for_lab,
)
from app.services.firecracker_paths import (
    PathContainmentError,
    lab_state_dir,
    validate_lab_id,
)
from app.services.port_allocator import allocate_novnc_port, release_novnc_port

logger = logging.getLogger(__name__)


# Path to the compose project to deploy inside the VM
COMPOSE_PROJECT_PATH = Path(__file__).parent.parent.parent.parent / "octolab-hackvm"


class FirecrackerRuntimeError(Exception):
    """Base exception for Firecracker runtime errors."""

    pass


class PreflightError(FirecrackerRuntimeError):
    """Raised when preflight checks fail."""

    pass


class VMBootError(FirecrackerRuntimeError):
    """Raised when VM fails to boot."""

    pass


class AgentError(FirecrackerRuntimeError):
    """Raised when agent communication fails."""

    pass


class ComposeError(FirecrackerRuntimeError):
    """Raised when compose operations fail inside VM."""

    pass


class NetworkError(FirecrackerRuntimeError):
    """Raised when network setup fails."""

    pass


def _truncate_diag(diag: dict) -> str:
    """Truncate diag output for safe logging.

    Args:
        diag: Diag response dict from agent

    Returns:
        Compact string representation (max 2KB), no secrets.
    """
    import json

    try:
        # Extract key fields only
        safe_diag = {
            "docker_ready": diag.get("docker_ready"),
            "summary": str(diag.get("summary", ""))[:200],
        }
        # Include last_compose_status if present
        if diag.get("last_compose_status"):
            lcs = diag["last_compose_status"]
            safe_diag["last_compose"] = {
                "success": lcs.get("success"),
                "error": str(lcs.get("error", ""))[:100] if lcs.get("error") else None,
            }
        return json.dumps(safe_diag)[:2048]
    except Exception:
        return str(diag)[:500]


class FirecrackerLabRuntime:
    """Firecracker microVM runtime implementation.

    Provides per-lab kernel isolation using Firecracker microVMs.
    Runs Docker Compose inside the VM to start the lab stack.

    Usage:
        runtime = FirecrackerLabRuntime()
        await runtime.create_lab(lab, recipe, db_session=session)
        # Lab is now running in isolated VM with Docker
        await runtime.destroy_lab(lab)

    IMPORTANT: NO FALLBACK
        If any step fails, this runtime raises an exception.
        It NEVER falls back to compose runtime.
    """

    def __init__(self) -> None:
        """Initialize the Firecracker runtime.

        Runs preflight checks on first lab creation, not here,
        to avoid blocking startup when runtime isn't being used.
        """
        self._preflight_checked = False
        self._preflight_result: PreflightResult | None = None

    def _ensure_preflight(self) -> PreflightResult:
        """Ensure preflight checks have been run.

        Returns:
            PreflightResult

        Raises:
            PreflightError: If preflight checks fail
        """
        if not self._preflight_checked:
            self._preflight_result = preflight()
            self._preflight_checked = True

            if not self._preflight_result.can_run:
                errors = ", ".join(self._preflight_result.errors)
                raise PreflightError(f"Firecracker preflight failed: {errors}")

            if self._preflight_result.warnings:
                for warning in self._preflight_result.warnings:
                    logger.warning(f"Firecracker preflight warning: {warning}")

        return self._preflight_result

    async def run_vm_diag(self, lab: Lab) -> dict:
        """Run diagnostic command on VM via agent.

        Args:
            lab: Lab model instance

        Returns:
            Diag response dict with docker_ready, last_compose_status, etc.
            On error: {"ok": False, "error": "diag_failed"}
        """
        lab_id = str(lab.id)
        try:
            resp = await send_agent_command(
                lab_id,
                "diag",
                timeout=settings.microvm_diag_timeout_secs,
            )
            if resp.ok:
                # Return the full response dict (includes docker_ready, last_compose_status)
                return {
                    "ok": True,
                    "docker_ready": getattr(resp, "docker_ready", None),
                    "last_compose_status": getattr(resp, "last_compose_status", None),
                    "summary": resp.stdout[:500] if resp.stdout else "",
                }
            else:
                return {"ok": False, "error": resp.error or "diag_returned_error"}
        except asyncio.TimeoutError:
            logger.error(f"diag timed out for lab ...{lab_id[-6:]}")
            return {"ok": False, "error": "diag_timeout"}
        except Exception as e:
            logger.error(f"diag failed for lab ...{lab_id[-6:]}: {type(e).__name__}")
            return {"ok": False, "error": "diag_failed"}

    async def compose_up_inside_vm(
        self,
        lab: Lab,
        project_name: str,
        timeout: float | None = None,
    ) -> None:
        """Run compose_up inside the VM via guest agent.

        This is the single abstraction for "tell the guest to start the lab".

        Args:
            lab: Lab model instance
            project_name: Docker compose project name
            timeout: Timeout in seconds (uses config default if None)

        Raises:
            ComposeError: If compose_up fails (with error details)

        SECURITY:
        - Uses vsock agent protocol
        - shell=False internally
        - Does NOT run docker on host
        """
        lab_id = str(lab.id)
        effective_timeout = timeout or settings.microvm_compose_timeout_secs

        logger.info(f"compose_up_inside_vm: lab=...{lab_id[-6:]}, project={project_name}")

        try:
            resp = await send_agent_command(
                lab_id,
                "compose_up",
                project=project_name,
                timeout=int(effective_timeout),
            )
        except asyncio.TimeoutError:
            # Host-side timeout
            diag = await self.run_vm_diag(lab)
            logger.error(f"compose_up timed out for lab ...{lab_id[-6:]}: {_truncate_diag(diag)}")
            raise ComposeError(f"compose_up timed out after {effective_timeout}s")

        if resp.ok:
            logger.info(f"compose_up succeeded for lab ...{lab_id[-6:]}")
            return

        # compose_up failed - gather diag and raise
        diag = await self.run_vm_diag(lab)
        logger.error(f"compose_up failed for lab ...{lab_id[-6:]}: {_truncate_diag(diag)}")

        error_msg = resp.error or resp.stderr[:500] if resp.stderr else "compose_up_failed"
        raise ComposeError(f"Compose up failed: {error_msg}")

    def _package_compose_project(self, lab_id: str, vnc_password: str) -> bytes:
        """Package the compose project for upload to guest.

        Creates a tar.gz containing the docker-compose.yml and necessary files.

        For Firecracker VMs, we use a simplified compose file with public images
        since the VM doesn't have access to local build contexts.

        Args:
            lab_id: Lab UUID string
            vnc_password: VNC password for the lab

        Returns:
            bytes: tar.gz content

        SECURITY:
        - Does NOT include secrets in the archive except VNC password
        - VNC password is required for VNC auth
        """
        # Create in-memory tar
        tar_buffer = io.BytesIO()

        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            # Generate a VM-friendly compose file using public images
            # The original compose file uses local build contexts that won't exist in the VM
            #
            # IMPORTANT: Use an image with a real VNC server for Guacamole integration.
            # dorowu/ubuntu-desktop-lxde-vnc provides:
            # - VNC server on port 5900 (for Guacamole)
            # - noVNC on port 80 (web fallback)
            # - VNC_PASSWORD environment variable for authentication
            compose_content = f"""# Auto-generated compose file for Firecracker VM
# Uses public images since VM doesn't have local build contexts

services:
  octobox:
    # Ubuntu desktop with VNC for Guacamole integration
    # VNC server (x11vnc) listens on port 5900
    # noVNC web interface on port 80
    image: dorowu/ubuntu-desktop-lxde-vnc:latest
    ports:
      # Expose VNC port for Guacamole
      - "0.0.0.0:5900:5900"
      # Also expose noVNC web interface for fallback/debugging
      - "0.0.0.0:6080:80"
    environment:
      - VNC_PASSWORD=${{VNC_PASSWORD}}
    restart: unless-stopped

  target-web:
    image: httpd:2.4
    restart: unless-stopped

networks:
  default:
    driver: bridge
"""
            logger.info(f"Generated VM-friendly compose for lab ...{lab_id[-6:]}")

            # Add compose file
            compose_info = tarfile.TarInfo(name="docker-compose.yml")
            compose_bytes = compose_content.encode()
            compose_info.size = len(compose_bytes)
            tar.addfile(compose_info, io.BytesIO(compose_bytes))

            # Add .env file with lab-specific values
            env_content = f"""LAB_ID={lab_id}
VNC_PASSWORD={vnc_password}
"""
            env_info = tarfile.TarInfo(name=".env")
            env_bytes = env_content.encode()
            env_info.size = len(env_bytes)
            tar.addfile(env_info, io.BytesIO(env_bytes))

        return tar_buffer.getvalue()

    async def create_lab(
        self,
        lab: Lab,
        recipe: Recipe,
        db_session: AsyncSession | None = None,
        vnc_password: str | None = None,
    ) -> None:
        """Provision a lab as a Firecracker microVM.

        Steps:
        1. Run preflight checks
        2. Allocate host port
        3. Set up networking (tap, bridge, iptables)
        4. Boot VM
        5. Wait for agent ready
        6. Upload compose project
        7. Run docker compose up
        8. Verify OctoBox is accessible

        Args:
            lab: Lab model instance
            recipe: Recipe model instance
            db_session: Database session for port allocation
            vnc_password: VNC password for the lab

        Raises:
            PreflightError: If preflight checks fail
            NetworkError: If network setup fails
            VMBootError: If VM fails to boot
            AgentError: If agent communication fails
            ComposeError: If compose operations fail

        SECURITY:
        - Runs preflight checks first
        - Creates isolated VM per lab
        - NO FALLBACK to compose on any failure
        """
        lab_id = str(lab.id)
        logger.info(
            f"lab_create runtime=firecracker lab_id={lab_id[-6:]} "
            f"user_id={str(lab.owner_id)[-6:]}"
        )

        # Ensure preflight passes
        self._ensure_preflight()

        # Run doctor check for fatal issues
        doctor = run_doctor()
        if not doctor.ok:
            raise PreflightError(f"Doctor check failed: {doctor.summary[:200]}")

        host_port: int | None = None
        network_config: NetworkConfig | None = None
        vm_booted = False

        try:
            # Allocate host port
            if db_session:
                host_port = await allocate_novnc_port(
                    db_session,
                    lab_id=lab.id,
                    owner_id=lab.owner_id,
                )
            else:
                # Use a default port for testing
                host_port = 6080

            logger.info(f"Allocated host port {host_port} for lab ...{lab_id[-6:]}")

            # Set up networking
            network_config = await setup_network_for_lab(lab_id, host_port)
            if not network_config:
                raise NetworkError("Failed to set up networking")

            logger.info(
                f"Network ready: tap={network_config.tap_name}, "
                f"guest_ip={network_config.guest_ip}"
            )

            # Boot VM with network config
            metadata = await create_vm(lab_id, network_config=network_config)
            vm_booted = True

            logger.info(
                f"VM booted: pid={metadata.pid}, cid={metadata.cid}, "
                f"lab=...{lab_id[-6:]}"
            )

            # Wait for agent
            ping_response = await send_agent_command(lab_id, "ping")
            if not ping_response.ok:
                raise AgentError(f"Agent ping failed: {ping_response.error}")

            # Verify agent identity (catches stale rootfs)
            if not ping_response.agent_version or not ping_response.rootfs_build_id:
                raise StaleRootfsError(
                    "Agent missing version/build_id fields. "
                    "Rootfs likely stale - rebuild with: "
                    "sudo infra/firecracker/build-rootfs.sh --with-kernel --deploy"
                )

            logger.info(
                f"Agent ready for lab ...{lab_id[-6:]}: "
                f"version={ping_response.agent_version}, "
                f"build={ping_response.rootfs_build_id}"
            )

            # Configure VM network (required for outbound connectivity)
            network_response = await send_agent_command(
                lab_id,
                "configure_network",
                guest_ip=network_config.guest_ip,
                netmask=network_config.netmask,
                gateway=network_config.gateway,
                dns=network_config.dns,
            )
            if not network_response.ok:
                raise NetworkError(
                    f"configure_network failed: {network_response.error or network_response.stderr[:200] if network_response.stderr else 'unknown'}"
                )
            logger.info(f"Network configured for lab ...{lab_id[-6:]}: ip={network_config.guest_ip}")

            # Set up port forwarding from host to VM (for VNC access via Guacamole)
            # Port 5900 is the VNC server port that Guacamole's guacd connects to
            await setup_port_forward_for_lab(lab_id, host_port, guest_port=5900)
            logger.info(f"Port forward set up for lab ...{lab_id[-6:]}: host:{host_port} -> guest:5900")

            # Verify VNC password
            if not vnc_password:
                raise ComposeError("VNC password required for Firecracker labs")

            # Package and upload compose project
            project_name = f"octolab_{lab_id}"
            project_data = self._package_compose_project(lab_id, vnc_password)
            project_b64 = base64.b64encode(project_data).decode()

            upload_response = await send_agent_command(
                lab_id,
                "upload_project",
                project=project_name,
                data=project_b64,
            )
            if not upload_response.ok:
                raise ComposeError(
                    f"Failed to upload project: {upload_response.error or upload_response.stderr[:200]}"
                )

            logger.info(f"Project uploaded for lab ...{lab_id[-6:]}")

            # Run compose up via the clean abstraction
            # This handles timeouts, diag on failure, and proper error messages
            await self.compose_up_inside_vm(lab, project_name)

            # Verify status
            status_response = await send_agent_command(lab_id, "status")
            if status_response.ok:
                logger.info(
                    f"Container status for lab ...{lab_id[-6:]}: "
                    f"{status_response.stdout[:200]}"
                )

            # TODO: Verify host port responds (TCP connect test)
            # For now, we trust compose up success

            # Store VNC connection info for Guacamole
            # DO NOT set connection_url here - Guacamole provisioner will set it
            # The port forwarding (host_port -> guest:5900) allows guacd to connect
            lab.novnc_host_port = host_port
            lab.hackvm_project = project_name

            # Store VNC connection info in runtime_meta for Guacamole provisioning
            # - vnc_host: The host that guacd can connect to (Docker host gateway)
            # - vnc_port: The forwarded port on the host
            # - guest_ip: VM's IP (for direct probing/debugging)
            # - guest_port: VNC port inside the VM (5900)
            lab.runtime_meta = {
                "guest_ip": network_config.guest_ip,
                "guest_port": 5900,
                "vnc_host": "172.17.0.1",  # Docker host gateway - reachable from guacd
                "vnc_port": host_port,
            }

            logger.info(
                f"Firecracker lab ...{lab_id[-6:]} ready at port {host_port}, "
                f"guest_ip={network_config.guest_ip}"
            )

        except StaleRootfsError as e:
            # Stale rootfs detected - cleanup and raise with clear error
            logger.error(
                f"Stale rootfs for Firecracker lab ...{lab_id[-6:]}: {e}"
            )

            # Best-effort cleanup
            if vm_booted:
                try:
                    await self.destroy_lab(lab)
                except Exception as cleanup_error:
                    logger.warning(
                        f"Cleanup failed for lab ...{lab_id[-6:]}: {type(cleanup_error).__name__}"
                    )
            elif network_config:
                await cleanup_network_for_lab(lab_id, network_config.tap_name)

            if host_port and db_session:
                try:
                    await release_novnc_port(db_session, lab_id=lab.id)
                except Exception:
                    pass

            # Re-raise StaleRootfsError for lab service to handle
            raise

        except Exception as e:
            # Cleanup on failure - NO FALLBACK TO COMPOSE
            logger.error(
                f"Failed to create Firecracker lab ...{lab_id[-6:]}: {type(e).__name__}"
            )

            # Best-effort cleanup
            if vm_booted:
                try:
                    await self.destroy_lab(lab)
                except Exception as cleanup_error:
                    logger.warning(
                        f"Cleanup failed for lab ...{lab_id[-6:]}: {type(cleanup_error).__name__}"
                    )
            elif network_config:
                # Only cleanup network if VM didn't boot
                await cleanup_network_for_lab(lab_id, network_config.tap_name)

            if host_port and db_session:
                try:
                    await release_novnc_port(db_session, lab_id=lab.id)
                except Exception:
                    pass

            # Re-raise - NO FALLBACK
            raise

    async def destroy_lab(self, lab: Lab) -> Any:
        """Destroy a Firecracker microVM lab.

        Steps:
        1. Send compose down to guest agent (best-effort)
        2. Stop VM process
        3. Clean up port forwarding (iptables DNAT rules)
        4. Clean up networking (TAP device)
        5. Remove state directory

        Args:
            lab: Lab model instance

        Returns:
            Dict with teardown result

        SECURITY: Ensures all VM resources are cleaned up.
        """
        lab_id = str(lab.id)
        logger.info(f"Destroying Firecracker lab ...{lab_id[-6:]}")

        results = {
            "compose_down": False,
            "vm_stopped": False,
            "network_cleaned": False,
            "state_cleaned": False,
        }

        # 1. Try to send compose down (best-effort)
        try:
            project_name = lab.hackvm_project or f"octolab_{lab_id}"
            response = await asyncio.wait_for(
                send_agent_command(lab_id, "compose_down", project=project_name),
                timeout=30.0,
            )
            results["compose_down"] = response.ok
            if response.ok:
                logger.info(f"Compose down completed for lab ...{lab_id[-6:]}")
        except Exception as e:
            logger.warning(
                f"Compose down failed for lab ...{lab_id[-6:]}: {type(e).__name__}"
            )

        # 2. Stop VM
        try:
            destroyed = await destroy_vm(lab_id)
            results["vm_stopped"] = destroyed
            if destroyed:
                logger.info(f"VM stopped for lab ...{lab_id[-6:]}")
        except PathContainmentError as e:
            logger.error(f"Path containment error during VM destroy: {e}")
        except Exception as e:
            logger.warning(f"VM destroy failed: {type(e).__name__}")

        # 3. Clean up port forwarding (best-effort)
        try:
            await cleanup_port_forward_for_lab(lab_id)
        except Exception as e:
            logger.warning(f"Port forward cleanup failed: {type(e).__name__}")

        # 4. Clean up networking (TAP device)
        try:
            tap_name = f"tap-{lab_id[-8:]}"
            await cleanup_network_for_lab(lab_id, tap_name)
            results["network_cleaned"] = True
            logger.info(f"Network cleaned for lab ...{lab_id[-6:]}")
        except Exception as e:
            logger.warning(f"Network cleanup failed: {type(e).__name__}")

        # 5. State directory is cleaned by destroy_vm
        results["state_cleaned"] = results["vm_stopped"]

        return {
            "runtime": "firecracker",
            "lab_id": lab_id[-6:],  # Redacted
            "success": all(results.values()),
            **results,
        }

    async def resources_exist_for_lab(self, lab: Lab) -> bool:
        """Check if Firecracker VM resources exist for a lab.

        Args:
            lab: Lab model instance

        Returns:
            True if VM state directory exists
        """
        try:
            lab_id = str(lab.id)
            state_dir = lab_state_dir(lab_id)
            return state_dir.exists()
        except Exception:
            return False

    async def get_lab_status(self, lab: Lab) -> dict[str, Any]:
        """Get status of a Firecracker VM lab.

        Args:
            lab: Lab model instance

        Returns:
            Dict with VM status information
        """
        lab_id = str(lab.id)

        try:
            state_dir = lab_state_dir(lab_id)
            if not state_dir.exists():
                return {
                    "exists": False,
                    "running": False,
                    "containers": [],
                }

            # Try to get container status
            try:
                response = await send_agent_command(lab_id, "status")
                if response.ok:
                    return {
                        "exists": True,
                        "running": True,
                        "containers": response.stdout,
                    }
            except Exception:
                pass

            # Try simple ping
            try:
                response = await send_agent_command(lab_id, "ping")
                running = response.ok
            except Exception:
                running = False

            return {
                "exists": True,
                "running": running,
                "state_dir_exists": state_dir.exists(),
            }

        except Exception as e:
            return {
                "exists": False,
                "running": False,
                "error": type(e).__name__,
            }

    def get_preflight_result(self) -> PreflightResult | None:
        """Get the cached preflight result.

        Returns:
            PreflightResult or None if not yet run
        """
        return self._preflight_result

    def run_preflight(self) -> PreflightResult:
        """Run or re-run preflight checks.

        Returns:
            PreflightResult
        """
        self._preflight_result = preflight()
        self._preflight_checked = True
        return self._preflight_result
