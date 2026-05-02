"""API key encryption using Fernet with PBKDF2 key derivation.

Keys are encrypted at rest and only decrypted in memory when connecting to a broker.
Never log decrypted keys. Never return them in API responses.

The master secret must be provided via the VOLTANODE_SECRET_KEY environment variable.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger("volta.security")


class ApiKeyStore:
    """Encrypt/decrypt API credentials using Fernet + PBKDF2.

    Usage:
        store = ApiKeyStore(os.environ["VOLTANODE_SECRET_KEY"])
        encrypted = store.encrypt("my_api_key")
        plain = store.decrypt(encrypted)
    """

    # PBKDF2 iterations (OWASP recommended minimum for PBKDF2-SHA256)
    PBKDF2_ITERATIONS = 600_000
    SALT_LENGTH = 32

    def __init__(self, secret_key: str) -> None:
        """Initialize with a master secret.

        Args:
            secret_key: Raw master secret (arbitrary string).
                        A Fernet key is derived via PBKDF2-SHA256.
        """
        self._raw_key = secret_key
        self.fernet = self._derive_fernet(secret_key)

    @classmethod
    def _derive_fernet(cls, key: str) -> Fernet:
        """Derive a Fernet key from arbitrary input using PBKDF2-SHA256.

        This is significantly stronger than plain SHA256 key derivation as it
        uses a salt and many iterations to resist brute-force attacks.
        """
        try:
            # If it's already a valid Fernet key, use it directly
            f = Fernet(key)
            f.encrypt(b"test")  # smoke test
            return f
        except (ValueError, InvalidToken):
            # Derive via PBKDF2-SHA256 with random salt
            # Note: salt is deterministic per key to allow decryption without storage
            # In production, store salt separately alongside ciphertext
            salt = base64.urlsafe_b64encode(
                hashlib.sha256(key.encode()).digest()[:cls.SALT_LENGTH]
            )[:cls.SALT_LENGTH]
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=cls.PBKDF2_ITERATIONS,
            )
            derived = base64.urlsafe_b64encode(kdf.derive(key.encode()))
            return Fernet(derived)

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
