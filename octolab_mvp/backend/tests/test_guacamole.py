"""Tests for Guacamole integration.

These tests verify:
1. Encryption helpers for password security
2. GuacClient service (mocked HTTP)
3. Connect endpoint behavior

No database access is needed - all dependencies are mocked.
"""

import os
import pytest

# Mark entire module as not requiring database
pytestmark = pytest.mark.no_db
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

import httpx


class TestEncryptionHelpers:
    """Tests for password encryption/decryption."""

    def test_encryption_roundtrip(self):
        """Test that encrypt -> decrypt returns original value."""
        # Generate a test key
        from cryptography.fernet import Fernet

        test_key = Fernet.generate_key().decode()

        with patch("app.helpers.crypto.settings") as mock_settings:
            mock_settings.guac_enc_key = test_key

            from app.helpers.crypto import encrypt_password, decrypt_password

            original = "test_password_123!@#"
            encrypted = encrypt_password(original)
            decrypted = decrypt_password(encrypted)

            assert decrypted == original
            assert encrypted != original  # Should be different
            assert len(encrypted) > len(original)  # Fernet adds overhead

    def test_encryption_different_each_time(self):
        """Test that encryption produces different ciphertext each time."""
        from cryptography.fernet import Fernet

        test_key = Fernet.generate_key().decode()

        with patch("app.helpers.crypto.settings") as mock_settings:
            mock_settings.guac_enc_key = test_key

            from app.helpers.crypto import encrypt_password

            password = "same_password"
            enc1 = encrypt_password(password)
            enc2 = encrypt_password(password)

            # Fernet includes random IV, so ciphertexts should differ
            assert enc1 != enc2

    def test_encryption_fails_without_key(self):
        """Test that encryption raises error when key not configured."""
        with patch("app.helpers.crypto.settings") as mock_settings:
            mock_settings.guac_enc_key = None

            from app.helpers.crypto import encrypt_password, EncryptionError

            with pytest.raises(EncryptionError) as exc_info:
                encrypt_password("test")

            assert "not configured" in str(exc_info.value)

    def test_decryption_fails_with_wrong_key(self):
        """Test that decryption fails with incorrect key."""
        from cryptography.fernet import Fernet

        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()

        with patch("app.helpers.crypto.settings") as mock_settings:
            mock_settings.guac_enc_key = key1

            from app.helpers.crypto import encrypt_password, decrypt_password, EncryptionError

            encrypted = encrypt_password("secret")

            # Now try to decrypt with wrong key
            mock_settings.guac_enc_key = key2

            with pytest.raises(EncryptionError) as exc_info:
                decrypt_password(encrypted)

            assert "invalid token" in str(exc_info.value).lower()

    def test_secure_password_generation(self):
        """Test secure password generation."""
        from app.helpers.crypto import generate_secure_password

        pwd1 = generate_secure_password(24)
        pwd2 = generate_secure_password(24)

        assert len(pwd1) == 24
        assert len(pwd2) == 24
        assert pwd1 != pwd2  # Should be different each time

        # Should not contain ambiguous chars
        for char in "l1IO0":
            assert char not in pwd1
            assert char not in pwd2


class TestGuacClient:
    """Tests for GuacClient service."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test health check returns True when server responds."""
        from app.services.guacamole_client import GuacClient

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            async with GuacClient(base_url="http://test") as client:
                result = await client.health_check()

            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test health check returns False on connection error."""
        from app.services.guacamole_client import GuacClient

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.RequestError("Connection failed")

            async with GuacClient(base_url="http://test") as client:
                result = await client.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_login_success(self):
        """Test successful login returns token."""
        from app.services.guacamole_client import GuacClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "authToken": "test_token_abc123",
            "username": "testuser",
            "dataSource": "postgresql",
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            async with GuacClient(base_url="http://test") as client:
                token = await client.login("testuser", "password")

            assert token.token == "test_token_abc123"
            assert token.username == "testuser"
            assert token.datasource == "postgresql"

    @pytest.mark.asyncio
    async def test_login_auth_failure(self):
        """Test login raises GuacAuthError on 401."""
        from app.services.guacamole_client import GuacClient, GuacAuthError

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            async with GuacClient(base_url="http://test") as client:
                with pytest.raises(GuacAuthError):
                    await client.login("baduser", "badpassword")

    @pytest.mark.asyncio
    async def test_create_connection(self):
        """Test connection creation returns identifier."""
        from app.services.guacamole_client import GuacClient, GuacToken

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "identifier": "123",
            "name": "test-connection",
            "protocol": "vnc",
        }

        token = GuacToken(token="abc", username="admin", datasource="postgresql")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            async with GuacClient(base_url="http://test") as client:
                conn = await client.create_connection(
                    token=token,
                    name="test-connection",
                    protocol="vnc",
                    hostname="octobox",
                    port=5900,
                )

            assert conn.identifier == "123"
            assert conn.name == "test-connection"
            assert conn.protocol == "vnc"

    def test_get_client_url(self):
        """Test client URL generation."""
        from app.services.guacamole_client import GuacClient

        client = GuacClient(base_url="http://localhost:8081/guacamole")
        url = client.get_client_url("42", "test_token")

        assert "http://localhost:8081/guacamole/#/client/" in url
        assert "?token=test_token" in url


class TestDockerNetworkHelper:
    """Tests for Docker network helper."""

    @pytest.mark.asyncio
    async def test_get_lab_network_name(self):
        """Test network name generation."""
        from app.services.docker_net import get_lab_network_name

        lab_id = uuid4()
        network_name = get_lab_network_name(lab_id)

        assert network_name == f"octolab_{lab_id}_lab_net"

    @pytest.mark.asyncio
    async def test_connect_container_success(self):
        """Test successful container connection."""
        from app.services.docker_net import connect_container_to_network

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("app.services.docker_net._run_docker_cmd") as mock_run:
            mock_run.return_value = mock_result

            result = await connect_container_to_network(
                "container1", "network1"
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_connect_container_already_connected(self):
        """Test container already connected is idempotent."""
        from app.services.docker_net import connect_container_to_network

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "endpoint with name container1 already exists"

        with patch("app.services.docker_net._run_docker_cmd") as mock_run:
            mock_run.return_value = mock_result

            result = await connect_container_to_network(
                "container1", "network1"
            )

            assert result is True  # Should still return True


class TestConnectEndpoint:
    """Tests for /labs/{id}/connect endpoint."""

    @pytest.mark.asyncio
    async def test_connect_guac_disabled(self):
        """Test connect returns 404 when Guacamole disabled."""
        from app.api.routes.labs import connect_to_lab
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = uuid4()

        mock_db = AsyncMock()

        with patch("app.api.routes.labs.settings") as mock_settings:
            mock_settings.guac_enabled = False

            with pytest.raises(HTTPException) as exc_info:
                await connect_to_lab(uuid4(), mock_user, mock_db)

            assert exc_info.value.status_code == 404
            assert "not enabled" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_connect_lab_not_found(self):
        """Test connect returns 404 when lab not found."""
        from app.api.routes.labs import connect_to_lab
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = uuid4()

        mock_db = AsyncMock()

        with patch("app.api.routes.labs.settings") as mock_settings, \
             patch("app.api.routes.labs.get_lab_for_user") as mock_get_lab:
            mock_settings.guac_enabled = True
            mock_get_lab.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await connect_to_lab(uuid4(), mock_user, mock_db)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_connect_lab_not_ready(self):
        """Test connect returns 409 when lab not ready."""
        from app.api.routes.labs import connect_to_lab
        from app.models.lab import LabStatus
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = uuid4()

        mock_lab = MagicMock()
        mock_lab.id = uuid4()
        mock_lab.status = LabStatus.PROVISIONING

        mock_db = AsyncMock()

        with patch("app.api.routes.labs.settings") as mock_settings, \
             patch("app.api.routes.labs.get_lab_for_user") as mock_get_lab:
            mock_settings.guac_enabled = True
            mock_get_lab.return_value = mock_lab

            with pytest.raises(HTTPException) as exc_info:
                await connect_to_lab(mock_lab.id, mock_user, mock_db)

            assert exc_info.value.status_code == 409
            assert "not ready" in exc_info.value.detail


class TestPostConnectEndpoint:
    """Tests for POST /labs/{id}/connect endpoint (returns JSON)."""

    @pytest.mark.asyncio
    async def test_post_connect_guac_disabled(self):
        """Test POST connect returns 404 when Guacamole disabled."""
        from app.api.routes.labs import get_lab_connect_url
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = uuid4()

        mock_db = AsyncMock()

        with patch("app.api.routes.labs.settings") as mock_settings:
            mock_settings.guac_enabled = False

            with pytest.raises(HTTPException) as exc_info:
                await get_lab_connect_url(uuid4(), mock_user, mock_db)

            assert exc_info.value.status_code == 404
            assert "not enabled" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_post_connect_lab_not_found(self):
        """Test POST connect returns 404 when lab not found."""
        from app.api.routes.labs import get_lab_connect_url
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = uuid4()

        mock_db = AsyncMock()

        with patch("app.api.routes.labs.settings") as mock_settings, \
             patch("app.api.routes.labs.get_lab_for_user") as mock_get_lab:
            mock_settings.guac_enabled = True
            mock_get_lab.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await get_lab_connect_url(uuid4(), mock_user, mock_db)

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_post_connect_lab_not_ready(self):
        """Test POST connect returns 409 when lab not ready."""
        from app.api.routes.labs import get_lab_connect_url
        from app.models.lab import LabStatus
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = uuid4()

        mock_lab = MagicMock()
        mock_lab.id = uuid4()
        mock_lab.status = LabStatus.PROVISIONING

        mock_db = AsyncMock()

        with patch("app.api.routes.labs.settings") as mock_settings, \
             patch("app.api.routes.labs.get_lab_for_user") as mock_get_lab:
            mock_settings.guac_enabled = True
            mock_get_lab.return_value = mock_lab

            with pytest.raises(HTTPException) as exc_info:
                await get_lab_connect_url(mock_lab.id, mock_user, mock_db)

            assert exc_info.value.status_code == 409
            assert "not ready" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_post_connect_missing_guac_credentials(self):
        """Test POST connect returns 409 when lab lacks Guacamole config."""
        from app.api.routes.labs import get_lab_connect_url
        from app.models.lab import LabStatus
        from fastapi import HTTPException

        mock_user = MagicMock()
        mock_user.id = uuid4()

        mock_lab = MagicMock()
        mock_lab.id = uuid4()
        mock_lab.status = LabStatus.READY
        mock_lab.guac_username = None
        mock_lab.guac_password_enc = None
        mock_lab.guac_connection_id = None

        mock_db = AsyncMock()

        with patch("app.api.routes.labs.settings") as mock_settings, \
             patch("app.api.routes.labs.get_lab_for_user") as mock_get_lab:
            mock_settings.guac_enabled = True
            mock_get_lab.return_value = mock_lab

            with pytest.raises(HTTPException) as exc_info:
                await get_lab_connect_url(mock_lab.id, mock_user, mock_db)

            assert exc_info.value.status_code == 409
            assert "not provisioned" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_post_connect_success_returns_redirect_url(self):
        """Test POST connect returns JSON with redirect_url on success."""
        from app.api.routes.labs import get_lab_connect_url
        from app.models.lab import LabStatus
        from app.services.guacamole_client import GuacToken

        mock_user = MagicMock()
        mock_user.id = uuid4()

        mock_lab = MagicMock()
        mock_lab.id = uuid4()
        mock_lab.status = LabStatus.READY
        mock_lab.guac_username = "lab_abc123"
        mock_lab.guac_password_enc = "encrypted_password"
        mock_lab.guac_connection_id = "42"

        mock_db = AsyncMock()
        mock_token = GuacToken(token="test_token_xyz", username="lab_abc123", datasource="postgresql")

        with patch("app.api.routes.labs.settings") as mock_settings, \
             patch("app.api.routes.labs.get_lab_for_user") as mock_get_lab, \
             patch("app.api.routes.labs.decrypt_password") as mock_decrypt, \
             patch("app.api.routes.labs.GuacClient") as mock_guac_class:

            mock_settings.guac_enabled = True
            mock_get_lab.return_value = mock_lab
            mock_decrypt.return_value = "decrypted_password"

            # Setup mock GuacClient context manager
            mock_guac_instance = AsyncMock()
            mock_guac_instance.health_check.return_value = True
            mock_guac_instance.login.return_value = mock_token
            # get_client_url is a sync method, not async, so use MagicMock
            mock_guac_instance.get_client_url = MagicMock(return_value="http://guac/client?token=test")

            mock_guac_class.return_value.__aenter__.return_value = mock_guac_instance
            mock_guac_class.return_value.__aexit__.return_value = None

            result = await get_lab_connect_url(mock_lab.id, mock_user, mock_db)

            assert result.redirect_url == "http://guac/client?token=test"


class TestGuacamoleProvisioner:
    """Tests for Guacamole provisioner service."""

    def test_get_guac_username(self):
        """Test username generation from lab ID."""
        from app.services.guacamole_provisioner import get_guac_username

        lab_id = uuid4()
        username = get_guac_username(lab_id)

        assert username.startswith("lab_")
        assert len(username) == 12  # "lab_" + 8 chars

    def test_get_guac_connection_name(self):
        """Test connection name generation from lab ID."""
        from app.services.guacamole_provisioner import get_guac_connection_name

        lab_id = uuid4()
        name = get_guac_connection_name(lab_id)

        assert name.startswith("octolab-")
        assert len(name) == 16  # "octolab-" + 8 chars

    @pytest.mark.asyncio
    async def test_provision_guacamole_disabled(self):
        """Test provisioning returns False when disabled."""
        from app.services.guacamole_provisioner import provision_guacamole_for_lab

        mock_lab = MagicMock()
        mock_lab.id = uuid4()

        mock_session = AsyncMock()

        with patch("app.services.guacamole_provisioner.settings") as mock_settings:
            mock_settings.guac_enabled = False

            result = await provision_guacamole_for_lab(mock_lab, mock_session)

            assert result is False

    @pytest.mark.asyncio
    async def test_check_guacamole_available_disabled(self):
        """Test availability check returns True when disabled."""
        from app.services.guacamole_provisioner import check_guacamole_available

        with patch("app.services.guacamole_provisioner.settings") as mock_settings:
            mock_settings.guac_enabled = False

            result = await check_guacamole_available()

            assert result is True  # "Available" because not needed
