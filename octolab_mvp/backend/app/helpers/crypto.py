"""Cryptographic helpers for secure password encryption.

SECURITY: Never log plaintext passwords or decrypted values.
"""

import logging
import secrets
import string

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""

    pass


def _get_fernet() -> Fernet:
    """Get Fernet instance from config.

    Returns:
        Fernet instance configured with GUAC_ENC_KEY

    Raises:
        EncryptionError: If GUAC_ENC_KEY is not configured
    """
    if not settings.guac_enc_key:
        raise EncryptionError(
            "GUAC_ENC_KEY is not configured. Cannot encrypt/decrypt Guacamole passwords."
        )
    try:
        # SECURITY: SecretStr requires .get_secret_value() to access the value
        return Fernet(settings.guac_enc_key.get_secret_value().encode())
    except Exception as e:
        raise EncryptionError(f"Invalid GUAC_ENC_KEY format: {type(e).__name__}")


def encrypt_password(plaintext: str) -> str:
    """Encrypt a password using Fernet symmetric encryption.

    Args:
        plaintext: The password to encrypt (NEVER log this value)

    Returns:
        Base64-encoded encrypted password string

    Raises:
        EncryptionError: If encryption fails
    """
    if not plaintext:
        raise EncryptionError("Cannot encrypt empty password")

    try:
        fernet = _get_fernet()
        encrypted = fernet.encrypt(plaintext.encode())
        return encrypted.decode()
    except EncryptionError:
        raise
    except Exception as e:
        # SECURITY: Don't include plaintext in error message
        raise EncryptionError(f"Encryption failed: {type(e).__name__}")


def decrypt_password(encrypted: str) -> str:
    """Decrypt a Fernet-encrypted password.

    Args:
        encrypted: Base64-encoded encrypted password string

    Returns:
        Decrypted plaintext password (NEVER log the return value)

    Raises:
        EncryptionError: If decryption fails (invalid key or corrupted data)
    """
    if not encrypted:
        raise EncryptionError("Cannot decrypt empty ciphertext")

    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted.encode())
        return decrypted.decode()
    except InvalidToken:
        raise EncryptionError("Decryption failed: invalid token (wrong key or corrupted data)")
    except EncryptionError:
        raise
    except Exception as e:
        raise EncryptionError(f"Decryption failed: {type(e).__name__}")


def generate_secure_password(length: int = 24) -> str:
    """Generate a cryptographically secure random password.

    Args:
        length: Password length (minimum 16, maximum 64)

    Returns:
        Random password with mixed case letters and digits

    Note:
        Excludes ambiguous characters (l, 1, I, O, 0) for readability
    """
    if length < 16:
        length = 16
    if length > 64:
        length = 64

    # Use URL-safe alphabet without ambiguous characters
    alphabet = string.ascii_letters + string.digits
    # Remove ambiguous chars: l, 1, I, O, 0
    alphabet = alphabet.translate(str.maketrans("", "", "l1IO0"))

    return "".join(secrets.choice(alphabet) for _ in range(length))
