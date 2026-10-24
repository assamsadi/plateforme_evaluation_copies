"""
Sécurité applicative : hachage des mots de passe (argon2) et gestion des
JWT (création, vérification, révocation via blacklist Redis).

Ce module ne connaît PAS les modèles du domaine (User, etc.) — il reçoit
et retourne des types simples (str, dict, UUID). Le couplage avec le
domaine se fait dans app/auth/, qui appelle ces fonctions. Cohérent avec
le principe de séparation stricte des responsabilités (§7 du résumé
d'architecture) : la logique cryptographique ne doit jamais fuiter dans
la couche métier, et inversement.
"""
import uuid
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

import jwt
import redis.asyncio as redis
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_password_hasher = PasswordHasher()
_redis_client = redis.from_url(str(settings.REDIS_URL), decode_responses=True, protocol=2)


# --- Mots de passe ---

def hash_password(plain_password: str) -> str:
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        _password_hasher.verify(hashed_password, plain_password)
        return True
    except VerifyMismatchError:
        return False


# --- JWT ---

class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def _create_token(
    subject: str,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,          # user_id
        "role": role,            # filtre grossier ; contrôles fins faits en DB
        "type": token_type,
        "jti": str(uuid.uuid4()),  # identifiant unique du token, requis pour la blacklist
        "iat": now,
        "exp": now + expires_delta,
        **(extra_claims or {}),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(
        subject=user_id,
        role=role,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: str, role: str) -> str:
    return _create_token(
        subject=user_id,
        role=role,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )


class TokenError(Exception):
    """Levée pour tout token invalide, expiré, ou révoqué."""
    pass


async def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("Token expiré") from e
    except jwt.InvalidTokenError as e:
        raise TokenError("Token invalide") from e

    if payload.get("type") != expected_type:
        raise TokenError(f"Type de token invalide : attendu {expected_type}")

    if await _is_blacklisted(payload["jti"]):
        raise TokenError("Token révoqué")

    return payload


# --- Révocation (blacklist Redis) ---
# Utilisée pour le logout serveur et l'invalidation forcée d'un refresh
# token compromis. On ne blackliste que les refresh tokens : les access
# tokens ont une durée de vie courte (60 min par défaut), le coût d'une
# vérification Redis à chaque requête ne se justifie pas pour eux.

_BLACKLIST_KEY_PREFIX = "revoked_token:"


async def revoke_refresh_token(jti: str, expires_in: timedelta) -> None:
    """
    `expires_in` doit correspondre au temps restant avant l'expiration
    naturelle du token, pour ne pas garder l'entrée en Redis indéfiniment.
    """
    key = f"{_BLACKLIST_KEY_PREFIX}{jti}"
    await _redis_client.set(key, "1", ex=int(expires_in.total_seconds()))


async def _is_blacklisted(jti: str) -> bool:
    key = f"{_BLACKLIST_KEY_PREFIX}{jti}"
    return await _redis_client.exists(key) == 1