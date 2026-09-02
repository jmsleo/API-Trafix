import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import jwt
import redis.exceptions
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.config.database import get_db
from api_trafix.config.redis import get_redis
from api_trafix.core.security import ACCESS_TOKEN_TYPE, decode_token
from api_trafix.models import OperatorSession, OperatorSessionStatus, User, UserRole
from api_trafix.services.shift_overlap import shift_covers_datetime

WIB = timezone(timedelta(hours=7))

bearer_scheme = HTTPBearer(auto_error=False)


def _blacklist_key(jti: str) -> str:
    return f"blacklist:{jti}"


async def _token_is_blacklisted(payload: dict) -> bool:
    jti = payload.get("jti")
    if not jti:
        return False
    try:
        r = await get_redis()
        return await r.get(_blacklist_key(jti)) is not None
    except redis.exceptions.RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan autentikasi tidak tersedia",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Belum terautentikasi",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _resolve_token_user(credentials.credentials, db)


async def _resolve_token_user(token: str, db: AsyncSession) -> User:
    """Resolve a JWT access token to an active user, or raise 401/403."""
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token telah kedaluwarsa",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jenis token tidak valid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if await _token_is_blacklisted(payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token telah dicabut",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pengguna tidak ditemukan",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.status.value != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akun tidak aktif",
        )
    return user


async def get_current_user_query(
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticate from ``?token=`` — for EventSource, which cannot set headers."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Parameter token tidak ditemukan",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _resolve_token_user(token, db)


def require_roles(*roles: UserRole) -> Callable:
    allowed = set(roles)

    async def _require(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hak akses tidak mencukupi",
            )
        return current_user

    return _require


get_current_admin = require_roles(UserRole.ADMIN)
get_current_finance = require_roles(UserRole.FINANCE)
get_current_operator = require_roles(UserRole.OPERATOR)
get_current_teknisi = require_roles(UserRole.TEKNISI)
get_current_admin_or_teknisi = require_roles(UserRole.ADMIN, UserRole.TEKNISI)


async def get_active_operator_session(
    current_user: User = Depends(get_current_operator),
    db: AsyncSession = Depends(get_db),
) -> OperatorSession:
    """The operator's open ``operator_sessions`` row, or 403.

    Every POS transaction is attributed to this session: the operator, shift
    and gate are taken from it instead of being trusted from the request body.
    The session is only usable while its shift window covers the current WIB
    time — a session opened on an earlier shift stops working once that shift
    ends.
    """
    session = await db.scalar(
        select(OperatorSession)
        .where(
            OperatorSession.user_id == current_user.id,
            OperatorSession.status == OperatorSessionStatus.ACTIVE,
        )
        .options(
            selectinload(OperatorSession.user),
            selectinload(OperatorSession.shift),
            selectinload(OperatorSession.gate),
        )
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tidak ada sesi operator aktif — mulai sesi terlebih dahulu sebelum mengoperasikan gerbang",
        )
    shift = session.shift
    if shift is None or not shift_covers_datetime(
        datetime.now(WIB),
        shift.start_time,
        shift.finish_time,
        shift.crosses_midnight,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Sesi kerja sudah di luar jam shift aktif. Mulai sesi kembali "
                "pada jam shift yang ditugaskan."
            ),
        )
    return session
