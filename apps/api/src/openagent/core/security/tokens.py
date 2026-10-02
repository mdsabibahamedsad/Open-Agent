import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional


def generate_token() -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a token using SHA-256 for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    """Verify a token against its hash using constant-time comparison."""
    expected_hash = hash_token(token)
    return secrets.compare_digest(expected_hash, token_hash)


def create_token_pair() -> tuple[str, str]:
    """Create a token and its hash. Returns (token, token_hash)."""
    token = generate_token()
    token_hash = hash_token(token)
    return token, token_hash


def create_expiration(minutes: int = 60) -> datetime:
    """Create an expiration datetime."""
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def is_expired(expires_at: datetime) -> bool:
    """Check if a datetime has expired."""
    return datetime.now(timezone.utc) > expires_at


class TokenManager:
    """Manages token generation, hashing, and verification."""
    
    def __init__(self, expiry_minutes: int = 60):
        self.expiry_minutes = expiry_minutes
    
    def create(self) -> tuple[str, str, datetime]:
        """Create a new token with expiration. Returns (token, token_hash, expires_at)."""
        token = generate_token()
        token_hash = hash_token(token)
        expires_at = create_expiration(self.expiry_minutes)
        return token, token_hash, expires_at
    
    def verify(self, token: str, token_hash: str, expires_at: datetime) -> bool:
        """Verify a token against its hash and check expiration."""
        if is_expired(expires_at):
            return False
        return verify_token(token, token_hash)


# Default token managers for common use cases
email_verification_tokens = TokenManager(expiry_minutes=1440)  # 24 hours
password_reset_tokens = TokenManager(expiry_minutes=60)  # 1 hour
session_tokens = TokenManager(expiry_minutes=10080)  # 7 days