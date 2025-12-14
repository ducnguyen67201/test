"""Guacamole provisioning service for lab environments.

This service handles the creation and teardown of Guacamole resources
(users, connections, permissions) for each lab.

SECURITY:
- Passwords are generated securely and encrypted before storage
- Connection parameters are server-derived only (no client input)
- All operations are scoped to specific labs
- Never log passwords, tokens, or credentials
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.helpers.crypto import encrypt_password, decrypt_password, generate_secure_password, EncryptionError
from app.models.lab import Lab
from app.services.guacamole_client import (
    GuacClient,
    GuacClientError,
    GuacAuthError,
    GuacConnectionError,
)
from app.services.guacamole_preflight import (
    guacamole_preflight,
    PreflightResult,
    PreflightClassification,
)
from app.services.docker_net import (
    connect_guacd_to_lab,
    disconnect_guacd_from_lab,
    preflight_netcheck,
    NetCheckStatus,
    VNC_INTERNAL_PORT,
)

logger = logging.getLogger(__name__)

# Use the single source of truth from docker_net
OCTOBOX_VNC_PORT = VNC_INTERNAL_PORT


def get_octobox_hostname(lab_id: UUID) -> str:
    """Get the Docker container hostname for a lab's OctoBox.

    Uses compose naming convention: {project}-{service}-{instance}

    IMPORTANT: We use the full container name instead of just "octobox" because
    guacd may be connected to multiple lab networks simultaneously. Using just
    "octobox" would be ambiguous - Docker DNS might resolve to any lab's octobox.
    The full container name is deterministic and resolves correctly.

    Args:
        lab_id: Lab UUID

    Returns:
        Container hostname like 'octolab_abc123-octobox-1'
    """
    return f"octolab_{lab_id}-octobox-1"


class GuacProvisioningError(Exception):
    """Error during Guacamole provisioning."""

    pass


def get_guac_username(lab_id: UUID) -> str:
    """Generate Guacamole username for a lab.

    Uses first 8 chars of lab ID for readability.

    Args:
        lab_id: Lab UUID

    Returns:
        Username like 'lab_a1b2c3d4'
    """
    return f"lab_{str(lab_id)[:8]}"


def get_guac_connection_name(lab_id: UUID) -> str:
    """Generate Guacamole connection name for a lab.

    Args:
        lab_id: Lab UUID

    Returns:
        Connection name like 'octolab-a1b2c3d4'
    """
    return f"octolab-{str(lab_id)[:8]}"


async def _run_preflight() -> PreflightResult:
    """Run Guacamole preflight check with configured credentials.

    Returns:
        PreflightResult

    Raises:
        GuacProvisioningError: If credentials not configured
    """
    if not settings.guac_admin_password:
        raise GuacProvisioningError(
            "GUAC_ADMIN_PASSWORD not configured. "
            "Set it in your .env.local file."
        )

    # SECURITY: SecretStr requires .get_secret_value() to access the value
    return await guacamole_preflight(
        base_url=settings.guac_base_url,
        admin_user=settings.guac_admin_user,
        admin_password=settings.guac_admin_password.get_secret_value(),
    )


def _preflight_error_message(result: PreflightResult) -> str:
    """Generate actionable error message from preflight result.

    Args:
        result: PreflightResult from preflight check

    Returns:
        Human-readable error message with hints
    """
    base_msg = f"Guacamole preflight failed: {result.classification.value}"

    # Add classification-specific context
    if result.classification == PreflightClassification.BASE_URL_WRONG:
        return (
            f"{base_msg}. "
            f"GUAC_BASE_URL appears misconfigured (got 404 on /api/tokens). "
            f"URL: {result.sanitized_base_url}. "
            "Ensure it ends with '/guacamole' (e.g., http://127.0.0.1:8081/guacamole)."
        )
    elif result.classification == PreflightClassification.CREDS_WRONG:
        return (
            f"{base_msg}. "
            "GUAC_ADMIN_USER or GUAC_ADMIN_PASSWORD is incorrect. "
            "Check your .env.local file."
        )
    elif result.classification == PreflightClassification.SERVER_5XX:
        return (
            f"{base_msg}. "
            f"Guacamole server returned HTTP {result.api_status}. "
            "Check Guacamole logs: docker compose -f infra/guacamole/docker-compose.yml logs guacamole"
        )
    elif result.classification == PreflightClassification.NETWORK_DOWN:
        return (
            f"{base_msg}. "
            f"Cannot reach Guacamole at {result.sanitized_base_url}. "
            "Ensure the Guacamole stack is running: make guac-up"
        )
    elif result.classification == PreflightClassification.GUI_UNREACHABLE:
        return (
            f"{base_msg}. "
            f"Guacamole GUI not responding at {result.sanitized_base_url}. "
            "If you see an ERROR page in the browser, run: make guac-reset"
        )
    else:
        return f"{base_msg}. {result.hint}"


async def provision_guacamole_for_lab(
    lab: Lab,
    session: AsyncSession,
) -> bool:
    """Provision Guacamole resources for a lab.

    Creates:
    1. Per-lab Guacamole user with random password
    2. VNC connection to the lab's OctoBox
    3. Permission grant for user to access connection
    4. Network connection for guacd to reach the lab

    Updates lab with:
    - guac_connection_id
    - guac_username
    - guac_password_enc (encrypted)
    - guac_connected_at
    - connection_url (pointing to /labs/{id}/connect)

    Args:
        lab: Lab instance (must have id)
        session: Database session for updates

    Returns:
        True if provisioning succeeded

    Raises:
        GuacProvisioningError: If provisioning fails critically
    """
    if not settings.guac_enabled:
        logger.debug(f"Guacamole disabled, skipping provisioning for lab {lab.id}")
        return False

    logger.info(f"Provisioning Guacamole for lab {lab.id}")

    # Run preflight check first (validates GUI + API before attempting provisioning)
    preflight_result = await _run_preflight()
    if not preflight_result.ok:
        error_msg = _preflight_error_message(preflight_result)
        logger.error(f"Guacamole preflight failed for lab {lab.id}: {preflight_result.classification.value}")
        raise GuacProvisioningError(error_msg)

    logger.debug(f"Guacamole preflight passed for lab {lab.id}")

    # Get VNC password from lab (generated and stored during runtime.create_lab)
    # This same password is used for both VNC authentication and Guacamole user
    if not lab.guac_password_enc:
        raise GuacProvisioningError(
            f"VNC password not found for lab {lab.id}. "
            "Password must be generated before Guacamole provisioning."
        )

    try:
        password = decrypt_password(lab.guac_password_enc)
    except EncryptionError as e:
        raise GuacProvisioningError(f"Failed to decrypt VNC password: {e}")

    # Generate credentials
    username = get_guac_username(lab.id)
    connection_name = get_guac_connection_name(lab.id)

    try:
        async with GuacClient() as guac:
            # Get admin token (preflight already validated creds work)
            try:
                admin_token = await guac.login_admin()
            except GuacAuthError:
                # This shouldn't happen if preflight passed, but handle it
                raise GuacProvisioningError(
                    "Guacamole admin authentication failed unexpectedly. "
                    "Preflight passed but login failed. Check for race conditions."
                )

            # Create per-lab user
            await guac.create_user(admin_token, username, password)

            # Determine VNC connection parameters based on lab runtime
            # Firecracker: Use host gateway + forwarded port (VM is not on Docker network)
            # Compose: Use container hostname + standard VNC port
            is_firecracker = lab.runtime == "firecracker" and lab.runtime_meta

            if is_firecracker:
                # Firecracker: Connect via host port forwarding
                # guacd reaches VM through Docker host gateway (172.17.0.1)
                vnc_hostname = lab.runtime_meta.get("vnc_host", "172.17.0.1")
                vnc_port = lab.runtime_meta.get("vnc_port", lab.novnc_host_port)
                logger.info(
                    f"Firecracker lab {lab.id}: Guacamole connecting to {vnc_hostname}:{vnc_port}"
                )
            else:
                # Docker Compose: Use container hostname on lab network
                vnc_hostname = get_octobox_hostname(lab.id)
                vnc_port = OCTOBOX_VNC_PORT

            connection = await guac.create_connection(
                token=admin_token,
                name=connection_name,
                protocol="vnc",
                hostname=vnc_hostname,
                port=vnc_port,
                # VNC-specific parameters
                # SECURITY: password is required - OctoBox VNC is authenticated in GUAC mode
                **{
                    "password": password,  # VNC authentication password
                    "color-depth": "24",
                    "cursor": "remote",
                    "swap-red-blue": "false",
                    "read-only": "false",
                },
            )

            # Grant user access to the connection
            await guac.grant_connection_permission(
                admin_token, username, connection.identifier
            )

            # Connect guacd to the lab network (Docker Compose only)
            # Firecracker labs use host port forwarding, no network attachment needed
            if not is_firecracker:
                if not await connect_guacd_to_lab(lab.id):
                    logger.warning(
                        f"Failed to connect guacd to lab {lab.id} network. "
                        "VNC connection may not work."
                    )

                # Run network connectivity preflight check (Docker Compose only)
                netcheck_result = await preflight_netcheck(lab.id)
                if not netcheck_result.ok:
                    logger.warning(
                        f"Network preflight check failed for lab {lab.id}: "
                        f"{netcheck_result.status.value} - {netcheck_result.message}"
                    )
                else:
                    logger.debug(f"Network preflight passed for lab {lab.id}: {netcheck_result.message}")

            # Update lab with Guacamole info
            # Note: guac_password_enc is already set by lab_service before calling this
            lab.guac_connection_id = connection.identifier
            lab.guac_username = username
            lab.guac_connected_at = datetime.now(timezone.utc)
            # Set connection_url to our auth gateway
            lab.connection_url = f"/labs/{lab.id}/connect"

            await session.commit()

            logger.info(
                f"Guacamole provisioned for lab {lab.id}: "
                f"user={username}, connection={connection.identifier}"
            )
            return True

    except GuacConnectionError as e:
        raise GuacProvisioningError(
            f"Cannot connect to Guacamole server: {e}"
        )
    except GuacClientError as e:
        raise GuacProvisioningError(f"Guacamole API error: {e}")


async def teardown_guacamole_for_lab(lab: Lab) -> bool:
    """Teardown Guacamole resources for a lab.

    Best-effort cleanup:
    1. Disconnect guacd from lab network
    2. Delete Guacamole connection
    3. Delete Guacamole user

    Args:
        lab: Lab instance with guac_* fields

    Returns:
        True if all cleanup succeeded, False if any step failed
    """
    if not settings.guac_enabled:
        return True

    if not lab.guac_username and not lab.guac_connection_id:
        logger.debug(f"No Guacamole resources to clean up for lab {lab.id}")
        return True

    logger.info(f"Tearing down Guacamole for lab {lab.id}")
    all_succeeded = True

    # Disconnect guacd from lab network (do this first)
    try:
        await disconnect_guacd_from_lab(lab.id)
    except Exception as e:
        logger.warning(
            f"Failed to disconnect guacd from lab {lab.id} network: {type(e).__name__}"
        )
        all_succeeded = False

    # Delete Guacamole resources
    try:
        async with GuacClient() as guac:
            if not await guac.health_check():
                logger.warning(
                    f"Guacamole server not reachable during teardown for lab {lab.id}"
                )
                return False

            try:
                admin_token = await guac.login_admin()
            except GuacAuthError:
                logger.warning(
                    f"Guacamole admin auth failed during teardown for lab {lab.id}"
                )
                return False

            # Delete connection
            if lab.guac_connection_id:
                if not await guac.delete_connection(admin_token, lab.guac_connection_id):
                    all_succeeded = False

            # Delete user
            if lab.guac_username:
                if not await guac.delete_user(admin_token, lab.guac_username):
                    all_succeeded = False

    except Exception as e:
        logger.warning(
            f"Error during Guacamole teardown for lab {lab.id}: {type(e).__name__}"
        )
        all_succeeded = False

    return all_succeeded


async def check_guacamole_available() -> bool:
    """Check if Guacamole server is available and functional.

    Uses preflight check to validate both GUI and API endpoints.
    Used during startup to validate configuration.

    Returns:
        True if Guacamole is reachable and API works, False otherwise
    """
    if not settings.guac_enabled:
        return True  # Not enabled, so "available" for our purposes

    try:
        result = await _run_preflight()
        if not result.ok:
            logger.warning(
                f"Guacamole availability check failed: {result.classification.value}. "
                f"Hint: {result.hint}"
            )
        return result.ok
    except GuacProvisioningError as e:
        logger.error(f"Guacamole availability check failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Guacamole availability check failed: {type(e).__name__}")
        return False
