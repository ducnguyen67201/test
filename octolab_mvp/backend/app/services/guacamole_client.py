"""Guacamole API client for managing connections and users.

SECURITY:
- Never log passwords, tokens, or sensitive credentials
- All API calls use redacted logging
- Tokens are short-lived and scoped to specific operations
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Default datasource for PostgreSQL backend
DATASOURCE = "postgresql"


class GuacClientError(Exception):
    """Base exception for Guacamole client errors."""

    pass


class GuacAuthError(GuacClientError):
    """Authentication failed."""

    pass


class GuacConnectionError(GuacClientError):
    """Connection to Guacamole server failed."""

    pass


class GuacAPIError(GuacClientError):
    """Guacamole API returned an error."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class GuacToken:
    """Guacamole authentication token."""

    token: str
    username: str
    datasource: str

    def __repr__(self) -> str:
        # SECURITY: Never expose token in repr
        return f"GuacToken(username={self.username!r}, datasource={self.datasource!r}, token=****)"


@dataclass
class GuacConnection:
    """Guacamole connection details."""

    identifier: str
    name: str
    protocol: str
    parent_identifier: str = "ROOT"


class GuacClient:
    """Async client for Apache Guacamole REST API.

    SECURITY: This client only uses admin credentials for provisioning.
    User-specific tokens are obtained separately via login().
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 10.0,
    ):
        """Initialize Guacamole client.

        Args:
            base_url: Guacamole base URL (defaults to settings.guac_base_url)
            timeout: HTTP request timeout in seconds
        """
        self.base_url = (base_url or settings.guac_base_url).rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GuacClient":
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GuacClient must be used as async context manager")
        return self._client

    async def health_check(self) -> bool:
        """Check if Guacamole server is reachable.

        Returns:
            True if server responds, False otherwise
        """
        try:
            # Use the root endpoint which reliably returns 200 when Guacamole is up
            response = await self.client.get(f"{self.base_url}/")
            # Any HTTP response means the server is up
            # 200 = normal, 401/403 = auth required, 404 = endpoint not found
            return response.status_code in (200, 401, 403, 404)
        except httpx.RequestError as e:
            logger.warning(f"Guacamole health check failed: {type(e).__name__}")
            return False

    async def login(self, username: str, password: str) -> GuacToken:
        """Authenticate and obtain API token.

        Args:
            username: Guacamole username
            password: Guacamole password (NEVER log this)

        Returns:
            GuacToken with auth token

        Raises:
            GuacAuthError: If authentication fails
            GuacConnectionError: If server is unreachable
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/api/tokens",
                data={
                    "username": username,
                    "password": password,
                },
            )

            if response.status_code == 200:
                data = response.json()
                logger.debug(f"Guacamole login successful for user: {username}")
                return GuacToken(
                    token=data["authToken"],
                    username=data.get("username", username),
                    datasource=data.get("dataSource", DATASOURCE),
                )

            if response.status_code in (401, 403):
                raise GuacAuthError(f"Authentication failed for user: {username}")

            raise GuacAPIError(
                f"Unexpected response from login: {response.status_code}",
                status_code=response.status_code,
            )

        except httpx.RequestError as e:
            raise GuacConnectionError(f"Failed to connect to Guacamole: {type(e).__name__}")

    async def login_admin(self) -> GuacToken:
        """Login as admin using configured credentials.

        Returns:
            GuacToken for admin user

        Raises:
            GuacAuthError: If admin credentials are invalid
            GuacClientError: If credentials not configured
        """
        if not settings.guac_admin_password:
            raise GuacClientError("GUAC_ADMIN_PASSWORD not configured")

        # SECURITY: SecretStr requires .get_secret_value() to access the value
        return await self.login(
            settings.guac_admin_user,
            settings.guac_admin_password.get_secret_value(),
        )

    async def create_user(
        self,
        token: GuacToken,
        username: str,
        password: str,
    ) -> dict[str, Any]:
        """Create a new Guacamole user.

        Args:
            token: Admin authentication token
            username: New user's username
            password: New user's password (NEVER log this)

        Returns:
            User object from API

        Raises:
            GuacAPIError: If user creation fails
        """
        user_data = {
            "username": username,
            "password": password,
            "attributes": {
                "disabled": "",
                "expired": "",
                "access-window-start": "",
                "access-window-end": "",
                "valid-from": "",
                "valid-until": "",
                "timezone": None,
            },
        }

        response = await self.client.post(
            f"{self.base_url}/api/session/data/{token.datasource}/users",
            params={"token": token.token},
            json=user_data,
        )

        if response.status_code in (200, 201):
            logger.info(f"Created Guacamole user: {username}")
            return response.json()

        if response.status_code == 400:
            # User might already exist
            error_msg = response.text
            if "already exists" in error_msg.lower():
                logger.warning(f"Guacamole user already exists: {username}")
                return {"username": username}
            raise GuacAPIError(f"Failed to create user: {error_msg}", response.status_code)

        raise GuacAPIError(
            f"Failed to create user {username}: HTTP {response.status_code}",
            response.status_code,
        )

    async def delete_user(self, token: GuacToken, username: str) -> bool:
        """Delete a Guacamole user.

        Args:
            token: Admin authentication token
            username: Username to delete

        Returns:
            True if deleted, False if not found
        """
        response = await self.client.delete(
            f"{self.base_url}/api/session/data/{token.datasource}/users/{username}",
            params={"token": token.token},
        )

        if response.status_code in (200, 204):
            logger.info(f"Deleted Guacamole user: {username}")
            return True

        if response.status_code == 404:
            logger.debug(f"Guacamole user not found for deletion: {username}")
            return False

        logger.warning(
            f"Failed to delete Guacamole user {username}: HTTP {response.status_code}"
        )
        return False

    async def create_connection(
        self,
        token: GuacToken,
        name: str,
        protocol: str,
        hostname: str,
        port: int,
        **extra_params: str,
    ) -> GuacConnection:
        """Create a VNC connection in Guacamole.

        Args:
            token: Admin authentication token
            name: Connection name
            protocol: Protocol (vnc, rdp, ssh)
            hostname: Target hostname
            port: Target port
            **extra_params: Additional connection parameters

        Returns:
            GuacConnection with identifier

        Raises:
            GuacAPIError: If connection creation fails
        """
        connection_data = {
            "parentIdentifier": "ROOT",
            "name": name,
            "protocol": protocol,
            "parameters": {
                "hostname": hostname,
                "port": str(port),
                **extra_params,
            },
            "attributes": {
                "max-connections": "",
                "max-connections-per-user": "1",
            },
        }

        response = await self.client.post(
            f"{self.base_url}/api/session/data/{token.datasource}/connections",
            params={"token": token.token},
            json=connection_data,
        )

        if response.status_code in (200, 201):
            data = response.json()
            conn_id = data.get("identifier")
            logger.info(f"Created Guacamole connection: {name} (id={conn_id})")
            return GuacConnection(
                identifier=conn_id,
                name=name,
                protocol=protocol,
            )

        raise GuacAPIError(
            f"Failed to create connection {name}: HTTP {response.status_code}",
            response.status_code,
        )

    async def delete_connection(self, token: GuacToken, connection_id: str) -> bool:
        """Delete a Guacamole connection.

        Args:
            token: Admin authentication token
            connection_id: Connection identifier

        Returns:
            True if deleted, False if not found
        """
        response = await self.client.delete(
            f"{self.base_url}/api/session/data/{token.datasource}/connections/{connection_id}",
            params={"token": token.token},
        )

        if response.status_code in (200, 204):
            logger.info(f"Deleted Guacamole connection: {connection_id}")
            return True

        if response.status_code == 404:
            logger.debug(f"Guacamole connection not found for deletion: {connection_id}")
            return False

        logger.warning(
            f"Failed to delete Guacamole connection {connection_id}: HTTP {response.status_code}"
        )
        return False

    async def grant_connection_permission(
        self,
        token: GuacToken,
        username: str,
        connection_id: str,
    ) -> bool:
        """Grant a user READ permission on a connection.

        Args:
            token: Admin authentication token
            username: User to grant permission
            connection_id: Connection to grant access to

        Returns:
            True if permission granted
        """
        # Guacamole uses JSON Patch format for permission updates
        permission_data = [
            {
                "op": "add",
                "path": f"/connectionPermissions/{connection_id}",
                "value": "READ",
            }
        ]

        response = await self.client.patch(
            f"{self.base_url}/api/session/data/{token.datasource}/users/{username}/permissions",
            params={"token": token.token},
            json=permission_data,
        )

        if response.status_code in (200, 204):
            logger.info(f"Granted connection {connection_id} to user {username}")
            return True

        logger.warning(
            f"Failed to grant connection permission: HTTP {response.status_code}"
        )
        return False

    def get_client_url(self, connection_id: str, token: str) -> str:
        """Build the Guacamole client URL for a connection.

        Args:
            connection_id: Connection identifier
            token: User's auth token (NEVER log this)

        Returns:
            Full URL to Guacamole client (uses guac_public_url for browser access)
        """
        # Guacamole encodes connection ID as base64 with datasource prefix
        # Format: {connection_id}\0c\0{datasource}
        import base64

        client_id = f"{connection_id}\x00c\x00{DATASOURCE}"
        encoded_id = base64.b64encode(client_id.encode()).decode()

        # Use public URL for browser access (not base_url which is for backend API calls)
        public_url = settings.guac_public_url.rstrip("/")
        return f"{public_url}/#/client/{encoded_id}?token={token}"
