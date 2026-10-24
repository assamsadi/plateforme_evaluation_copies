"""
Thin wrapper around app/core/security.py to maintain domain boundaries for the auth module.
"""
from datetime import timedelta
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    revoke_refresh_token,
    hash_password,
    verify_password,
    TokenType,
    TokenError,
    _create_token,
)

def create_mfa_token(user_id: str, role: str) -> str:
    return _create_token(
        subject=user_id,
        role=role,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=5),
        extra_claims={"mfa_pending": True}
    )

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "revoke_refresh_token",
    "hash_password",
    "verify_password",
    "TokenType",
    "TokenError",
    "create_mfa_token",
]
