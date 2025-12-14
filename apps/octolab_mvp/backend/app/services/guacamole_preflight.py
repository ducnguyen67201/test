"""Guacamole functional readiness checker (preflight).

Validates that Guacamole is truly operational before attempting provisioning:
1. GUI endpoint reachable (GET base_url/ returns HTML)
2. API tokens endpoint works (POST base_url/api/tokens returns 200)

SECURITY:
- Never log admin passwords, tokens, or credentials
- All error messages use redacted/sanitized values
- Classifications provide actionable hints without exposing secrets
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)


class PreflightClassification(Enum):
    """Classification of preflight failure causes."""

    OK = "ok"
    BASE_URL_WRONG = "base_url_wrong"  # 404 on /api/tokens => URL misconfigured
    CREDS_WRONG = "creds_wrong"  # 401/403 on /api/tokens => bad credentials
    SERVER_5XX = "server_5xx"  # >= 500 => Guacamole server error
    NETWORK_DOWN = "network_down"  # Connection refused, DNS, timeout
    GUI_UNREACHABLE = "gui_unreachable"  # Base URL doesn't serve GUI
    UNKNOWN = "unknown"


# Human-readable hints for each classification
CLASSIFICATION_HINTS = {
    PreflightClassification.OK: "Guacamole is ready.",
    PreflightClassification.BASE_URL_WRONG: (
        "Guacamole base URL appears misconfigured. "
        "Check GUAC_BASE_URL - it should end with '/guacamole' (e.g., http://127.0.0.1:8081/guacamole). "
        "Got 404 on /api/tokens endpoint."
    ),
    PreflightClassification.CREDS_WRONG: (
        "Guacamole admin credentials are invalid. "
        "Check GUAC_ADMIN_USER and GUAC_ADMIN_PASSWORD in your .env.local file."
    ),
    PreflightClassification.SERVER_5XX: (
        "Guacamole server returned a 5xx error. "
        "Check Guacamole container logs: docker compose logs guacamole"
    ),
    PreflightClassification.NETWORK_DOWN: (
        "Cannot reach Guacamole server. "
        "Ensure the Guacamole stack is running: make guac-up"
    ),
    PreflightClassification.GUI_UNREACHABLE: (
        "Guacamole GUI endpoint is not responding. "
        "The server may still be starting, or GUAC_BASE_URL is wrong. "
        "If you see a generic ERROR page, run: make guac-reset"
    ),
    PreflightClassification.UNKNOWN: (
        "Unexpected error during Guacamole preflight check. "
        "Check container logs: docker compose -f infra/guacamole/docker-compose.yml logs"
    ),
}


@dataclass
class PreflightResult:
    """Result of Guacamole preflight check."""

    ok: bool
    gui_ok: bool
    api_ok: bool
    classification: PreflightClassification
    hint: str
    sanitized_base_url: str
    gui_status: Optional[int] = None
    api_status: Optional[int] = None
    error_detail: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"PreflightResult(ok={self.ok}, gui_ok={self.gui_ok}, api_ok={self.api_ok}, "
            f"classification={self.classification.value}, sanitized_url={self.sanitized_base_url!r})"
        )


def sanitize_url(url: str) -> str:
    """Sanitize URL for safe logging (remove any embedded credentials).

    Args:
        url: URL that may contain credentials

    Returns:
        URL with password redacted
    """
    try:
        parsed = urlparse(url)
        if parsed.password:
            # Redact password
            netloc = f"{parsed.username}:****@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
        return url
    except Exception:
        # If parsing fails, return a safe placeholder
        return "<invalid-url>"


def normalize_base_url(url: str) -> str:
    """Normalize Guacamole base URL.

    Ensures URL ends with /guacamole if it's a bare host.
    Removes trailing slashes for consistency.

    Args:
        url: Raw base URL

    Returns:
        Normalized URL
    """
    url = url.rstrip("/")

    # If URL doesn't end with a path component that looks like guacamole,
    # the user may have misconfigured it (we don't auto-add though)
    return url


def build_url(base: str, path: str) -> str:
    """Safely join base URL and path without double slashes.

    Args:
        base: Base URL (e.g., http://localhost:8081/guacamole)
        path: Path to append (e.g., /api/tokens)

    Returns:
        Joined URL
    """
    # Ensure base ends with / for proper urljoin behavior
    if not base.endswith("/"):
        base = base + "/"
    # Remove leading / from path to avoid double slashes
    path = path.lstrip("/")
    return urljoin(base, path)


async def check_gui_reachable(
    client: httpx.AsyncClient,
    base_url: str,
) -> tuple[bool, Optional[int], Optional[str]]:
    """Check if Guacamole GUI is reachable.

    Args:
        client: HTTP client
        base_url: Guacamole base URL

    Returns:
        Tuple of (success, status_code, error_detail)
    """
    gui_url = build_url(base_url, "/")
    try:
        # Don't follow redirects - accept 302 as success (redirect to login is fine)
        response = await client.get(gui_url, follow_redirects=False)
        # Accept 200 or 302 as success (302 may redirect to login)
        if response.status_code in (200, 302):
            return (True, response.status_code, None)
        return (False, response.status_code, f"HTTP {response.status_code}")
    except httpx.ConnectError:
        return (False, None, "Connection refused")
    except httpx.TimeoutException:
        return (False, None, "Connection timeout")
    except httpx.RequestError as e:
        return (False, None, type(e).__name__)


async def check_api_tokens(
    client: httpx.AsyncClient,
    base_url: str,
    username: str,
    password: str,
) -> tuple[bool, Optional[int], Optional[str], PreflightClassification]:
    """Check if Guacamole API tokens endpoint works.

    Args:
        client: HTTP client
        base_url: Guacamole base URL
        username: Admin username
        password: Admin password (NEVER log this)

    Returns:
        Tuple of (success, status_code, error_detail, classification)
    """
    api_url = build_url(base_url, "api/tokens")
    try:
        response = await client.post(
            api_url,
            data={
                "username": username,
                "password": password,
            },
        )

        if response.status_code == 200:
            return (True, 200, None, PreflightClassification.OK)

        # Classify the failure
        if response.status_code == 404:
            return (False, 404, "API endpoint not found", PreflightClassification.BASE_URL_WRONG)

        if response.status_code in (401, 403):
            return (False, response.status_code, "Authentication failed", PreflightClassification.CREDS_WRONG)

        if response.status_code >= 500:
            return (False, response.status_code, f"Server error {response.status_code}", PreflightClassification.SERVER_5XX)

        return (False, response.status_code, f"HTTP {response.status_code}", PreflightClassification.UNKNOWN)

    except httpx.ConnectError:
        return (False, None, "Connection refused", PreflightClassification.NETWORK_DOWN)
    except httpx.TimeoutException:
        return (False, None, "Connection timeout", PreflightClassification.NETWORK_DOWN)
    except httpx.RequestError as e:
        return (False, None, type(e).__name__, PreflightClassification.NETWORK_DOWN)


async def guacamole_preflight(
    base_url: str,
    admin_user: str,
    admin_password: str,
    timeout: float = 10.0,
) -> PreflightResult:
    """Perform Guacamole functional readiness check.

    Checks:
    1. GUI endpoint reachable (GET base_url/)
    2. API tokens endpoint works (POST base_url/api/tokens with credentials)

    Args:
        base_url: Guacamole base URL
        admin_user: Admin username
        admin_password: Admin password (NEVER logged)
        timeout: HTTP timeout in seconds

    Returns:
        PreflightResult with status and classification
    """
    base_url = normalize_base_url(base_url)
    sanitized_url = sanitize_url(base_url)

    logger.debug(f"Guacamole preflight check starting for: {sanitized_url}")

    async with httpx.AsyncClient(timeout=timeout) as client:
        # Step 1: Check GUI reachable
        gui_ok, gui_status, gui_error = await check_gui_reachable(client, base_url)

        if not gui_ok:
            # GUI not reachable - determine if network issue
            if gui_error in ("Connection refused", "Connection timeout"):
                classification = PreflightClassification.NETWORK_DOWN
            else:
                classification = PreflightClassification.GUI_UNREACHABLE

            return PreflightResult(
                ok=False,
                gui_ok=False,
                api_ok=False,
                classification=classification,
                hint=CLASSIFICATION_HINTS[classification],
                sanitized_base_url=sanitized_url,
                gui_status=gui_status,
                error_detail=gui_error,
            )

        # Step 2: Check API tokens endpoint
        api_ok, api_status, api_error, classification = await check_api_tokens(
            client, base_url, admin_user, admin_password
        )

        if api_ok:
            return PreflightResult(
                ok=True,
                gui_ok=True,
                api_ok=True,
                classification=PreflightClassification.OK,
                hint=CLASSIFICATION_HINTS[PreflightClassification.OK],
                sanitized_base_url=sanitized_url,
                gui_status=gui_status,
                api_status=api_status,
            )

        return PreflightResult(
            ok=False,
            gui_ok=True,
            api_ok=False,
            classification=classification,
            hint=CLASSIFICATION_HINTS[classification],
            sanitized_base_url=sanitized_url,
            gui_status=gui_status,
            api_status=api_status,
            error_detail=api_error,
        )


async def guacamole_preflight_from_settings() -> PreflightResult:
    """Perform preflight check using application settings.

    Convenience function that loads credentials from settings.

    Returns:
        PreflightResult

    Raises:
        ValueError: If Guacamole is disabled or credentials not configured
    """
    from app.config import settings

    if not settings.guac_enabled:
        raise ValueError("Guacamole integration is disabled (GUAC_ENABLED=false)")

    if not settings.guac_admin_password:
        raise ValueError("GUAC_ADMIN_PASSWORD not configured")

    # SECURITY: SecretStr requires .get_secret_value() to access the value
    return await guacamole_preflight(
        base_url=settings.guac_base_url,
        admin_user=settings.guac_admin_user,
        admin_password=settings.guac_admin_password.get_secret_value(),
    )
