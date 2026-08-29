from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.account import Account
from app.models.user import User
from app.schemas.user import LogoutRequest, RefreshRequest, Token, UserCreate, UserResponse
from app.services.audit_service import log_action
from app.services.refresh_token_service import (
    RefreshTokenInvalid,
    RefreshTokenReused,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, payload: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        await log_action(db, request=request, action="register_failed_duplicate_email", detail=payload.email)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    await db.flush()  # get user.id before creating the dependent account

    account = Account(user_id=user.id, balance=Decimal("0.00"))
    db.add(account)

    await log_action(db, request=request, action="register", user_id=user.id, detail=user.email)

    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    # OAuth2PasswordRequestForm uses "username" as the field name; we treat it as email.
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(form_data.password, user.hashed_password):
        await log_action(
            db,
            request=request,
            action="login_failed",
            user_id=user.id if user else None,
            detail=form_data.username,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await log_action(db, request=request, action="login_success", user_id=user.id)

    access_token = create_access_token(subject=str(user.id))
    refresh_token = await issue_refresh_token(db, user.id)
    await db.commit()

    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=Token)
@limiter.limit("20/minute")
async def refresh(request: Request, payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        user_id, new_refresh_token = await rotate_refresh_token(db, payload.refresh_token)
    except RefreshTokenReused:
        await log_action(db, request=request, action="refresh_token_reuse_detected", detail="all sessions revoked")
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected — all sessions have been revoked, please log in again",
        )
    except RefreshTokenInvalid:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    await log_action(db, request=request, action="token_refreshed")
    await db.commit()

    new_access_token = create_access_token(subject=user_id)
    return Token(access_token=new_access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest, db: AsyncSession = Depends(get_db)):
    await revoke_refresh_token(db, payload.refresh_token)
    await db.commit()
    return None
