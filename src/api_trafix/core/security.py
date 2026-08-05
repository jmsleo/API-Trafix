import uuid
from datetime import datetime, timedelta, timezone

import jwt
from werkzeug.security import check_password_hash, generate_password_hash

from api_trafix.config.settings import get_settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"

settings = get_settings()


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return check_password_hash(hashed, password)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _create_token(user_id: str, role: str, token_type: str, expires_delta: timedelta, jti: str | None = None) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "type": token_type,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": _now(),
        "exp": _now() + expires_delta,
    }
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    token = _create_token(
        user_id,
        role,
        ACCESS_TOKEN_TYPE,
        timedelta(minutes=settings.access_token_expire_minutes),
        jti=jti,
    )
    return token, jti


def create_refresh_token(user_id: str, role: str) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    token = _create_token(
        user_id,
        role,
        REFRESH_TOKEN_TYPE,
        timedelta(days=settings.refresh_token_expire_days),
        jti=jti,
    )
    return token, jti


def access_token_expire_seconds() -> int:
    return settings.access_token_expire_minutes * 60


def refresh_token_expire_seconds() -> int:
    return settings.refresh_token_expire_days * 24 * 3600


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
