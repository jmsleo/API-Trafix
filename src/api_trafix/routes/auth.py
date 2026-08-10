import jwt
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.config.redis import get_redis
from api_trafix.core.dependencies import get_current_user
from api_trafix.core.ratelimit import (
    clear_login_throttle,
    enforce_login_throttle,
    record_failed_login,
)
from api_trafix.core.security import (
    REFRESH_TOKEN_TYPE,
    access_token_expire_seconds,
    create_access_token,
    create_refresh_token,
    decode_token,
    refresh_token_expire_seconds,
    verify_password,
)
from api_trafix.models import User
from api_trafix.schemas import LoginRequest, LogoutRequest, RefreshRequest, TokenPair
from api_trafix.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid username or password",
    headers={"WWW-Authenticate": "Bearer"},
)

INVALID_REFRESH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired refresh token",
    headers={"WWW-Authenticate": "Bearer"},
)


def _refresh_key(jti: str) -> str:
    return f"refresh:{jti}"


def _blacklist_key(jti: str) -> str:
    return f"blacklist:{jti}"


async def _store_refresh_jti(jti: str, user_id: str) -> None:
    r = await get_redis()
    await r.setex(_refresh_key(jti), refresh_token_expire_seconds(), user_id)


async def _consume_refresh_jti(jti: str) -> str | None:
    r = await get_redis()
    value = await r.get(_refresh_key(jti))
    if value is not None:
        await r.delete(_refresh_key(jti))
    return value


@router.post("/login", response_model=TokenPair)
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    await enforce_login_throttle(request, data.username)

    result = await db.execute(
        select(User).where(func.lower(User.username) == data.username.lower())
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(data.password, user.password):
        await record_failed_login(data.username)
        raise INVALID_CREDENTIALS

    if user.status.value != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    await clear_login_throttle(data.username)
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    role = user.role.value
    access_token, _ = create_access_token(str(user.id), role)
    refresh_token, jti = create_refresh_token(str(user.id), role)
    await _store_refresh_jti(jti, str(user.id))

    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest):
    try:
        payload = decode_token(data.refresh_token)
    except jwt.ExpiredSignatureError:
        raise INVALID_REFRESH
    except jwt.InvalidTokenError:
        raise INVALID_REFRESH

    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise INVALID_REFRESH

    user_id = payload.get("sub")
    if user_id is None:
        raise INVALID_REFRESH

    jti = payload.get("jti")
    if not jti:
        raise INVALID_REFRESH

    stored_user_id = await _consume_refresh_jti(jti)
    if stored_user_id != user_id:
        raise INVALID_REFRESH

    access_token, _ = create_access_token(user_id, payload.get("role", ""))
    new_refresh_token, new_jti = create_refresh_token(user_id, payload.get("role", ""))
    await _store_refresh_jti(new_jti, user_id)

    return TokenPair(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: LogoutRequest):
    try:
        payload = decode_token(data.refresh_token)
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError):
        raise INVALID_REFRESH

    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise INVALID_REFRESH

    jti = payload.get("jti")
    if jti:
        await _consume_refresh_jti(jti)

    if data.access_token:
        try:
            access_payload = decode_token(data.access_token)
        except (jwt.InvalidTokenError, jwt.ExpiredSignatureError):
            access_payload = None
        if access_payload:
            access_jti = access_payload.get("jti")
            if access_jti:
                r = await get_redis()
                await r.setex(_blacklist_key(access_jti), access_token_expire_seconds(), "1")


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
