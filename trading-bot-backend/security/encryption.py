"""API key encryption using Fernet (symmetric AES-128 in CBC mode via HMAC).

Keys are encrypted at rest and only decrypted in memory when connecting to a broker.
Never log decrypted keys. Never return them in API responses.

The encryption key must be provided via the VOLTANODE_SECRET_KEY environment variable.
It should be a base64-encoded 32-byte Fernet key.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("volta.security")


class ApiKeyStore:
    """Encrypt/decrypt API credentials using Fernet.

    Usage:
        store = ApiKeyStore(os.environ["VOLTANODE_SECRET_KEY"])
        encrypted = store.encrypt("my_api_key")
        plain = store.decrypt(encrypted)
    """

    def __init__(self, secret_key: str) -> None:
        """Initialize with a Fernet-compatible key.

        Args:
            secret_key: A URL-safe base64-encoded 32-byte key, or a raw
                string that will be padded/hashed into a valid Fernet key.
        """
        self._raw_key = secret_key
        self.fernet = self._make_fernet(secret_key)

    @staticmethod
    def _make_fernet(key: str) -> Fernet:
        """Ensure the key is Fernet-compatible.

        If the key is not a valid 32-byte base64 string, derive one via
        base64-encoding the first 32 bytes of a SHA256 hash.
        """
        try:
            # If it's already a valid Fernet key, use it directly
            f = Fernet(key)
            f.encrypt(b"test")  # smoke test
            return f
        except (ValueError, InvalidToken):
            # Derive a valid key from arbitrary input
            import hashlib
            digest = hashlib.sha256(key.encode()).digest()
            encoded = base64.urlsafe_b64encode(digest)
            return Fernet(encoded)

    def encrypt(self, plain_text: str) -> str:
        """Encrypt a plaintext string.

        Args:
            plain_text: API key or secret to encrypt.

        Returns:
            URL-safe base64 ciphertext string.
        """
        return self.fernet.encrypt(plain_text.encode()).decode()

    def decrypt(self, cipher_text: str) -> str:
        """Decrypt a ciphertext string.

        Args:
            cipher_text: Encrypted string from encrypt().

        Returns:
            Original plaintext string.

        Raises:
            InvalidToken: If decryption fails (wrong key or corrupted data).
        """
        return self.fernet.decrypt(cipher_text.encode()).decode()

    @classmethod
    def from_env(cls, env_var: str = "VOLTANODE_SECRET_KEY") -> "ApiKeyStore":
        """Create an ApiKeyStore from an environment variable.

        Args:
            env_var: Name of the environment variable holding the secret key.

        Returns:
            ApiKeyStore instance.

        Raises:
            RuntimeError: If the environment variable is not set.
        """
        key = os.environ.get(env_var)
        if not key:
            raise RuntimeError(
                f"Environment variable {env_var} is not set. "
                "Set it to a secure random string before starting live trading."
            )
        return cls(key)

    def rotate_key(self, new_secret_key: str, encrypted_values: list) -> list:
        """Re-encrypt a list of ciphertexts with a new key.

        Useful for key rotation operations.

        Args:
            new_secret_key: The new Fernet-compatible key.
            encrypted_values: List of current ciphertext strings.

        Returns:
            List of re-encrypted strings.
        """
        new_store = ApiKeyStore(new_secret_key)
        results = []
        for val in encrypted_values:
            plain = self.decrypt(val)
            results.append(new_store.encrypt(plain))
        return results
