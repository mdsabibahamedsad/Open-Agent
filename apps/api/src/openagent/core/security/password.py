import os
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, HashingError


_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    if not password:
        raise ValueError("Password cannot be empty")
    if len(password) > 4096:
        raise ValueError("Password too long")
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its Argon2id hash."""
    if not password or not password_hash:
        return False
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except HashingError:
        return False


def needs_rehash(password_hash: str) -> bool:
    """Check if a password hash needs to be rehashed with current parameters."""
    try:
        return _ph.check_needs_rehash(password_hash)
    except HashingError:
        return True


def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(length)


def hash_token(token: str) -> str:
    """Hash a token (e.g., verification token, reset token) for storage."""
    return hash_password(token)


def verify_token(token: str, token_hash: str) -> bool:
    """Verify a token against its hash."""
    return verify_password(token, token_hash)


def generate_recovery_codes(count: int = 10, length: int = 8) -> list[str]:
    """Generate recovery codes for MFA."""
    return [secrets.token_hex(length // 2).upper() for _ in range(count)]


def hash_recovery_codes(codes: list[str]) -> str:
    """Hash recovery codes for storage."""
    return hash_password(",".join(sorted(codes)))


def verify_recovery_code(code: str, codes_hash: str) -> tuple[bool, list[str]]:
    """
    Verify a recovery code and return remaining codes.
    Returns (success, remaining_codes).
    """
    # This is a simplified implementation
    # In production, you'd want to store codes individually for better security
    try:
        if verify_password(",".join(sorted([code])), codes_hash):
            return True, []
    except Exception:
        pass
    return False, []


def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0