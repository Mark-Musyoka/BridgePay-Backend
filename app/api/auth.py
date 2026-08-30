from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.repositories.account_repository import AccountRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import (
    LogoutRequest,
    RefreshRequest,
    Token,
    UserCreate,
    UserResponse,
    VerifyEmailRequest,
)
from app.services.audit_service import log_action
from app.services.email_verification_service import (
    EmailVerificationTokenInvalid,
    confirm_verification_token,
    issue_verification_token,
)
from app.services.refresh_token_service import (
    RefreshTokenInvalid,
    RefreshTokenReused,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.tasks.email_tasks import send_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, payload: UserCreate, db: AsyncSession = Depends(get_db)):
    user_repo = UserRepository(db)

    existing = await user_repo.get_by_email(payload.email)
    if existing is not None:
        await log_action(db, request=request, action="register_failed_duplicate_email", detail=payload.email)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = await user_repo.create(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    await AccountRepository(db).create(user_id=user.id)

    raw_verification_token = await issue_verification_token(db, user.id)

    await log_action(db, request=request, action="register", user_id=user.id, detail=user.email)

    await db.commit()
    await db.refresh(user)

    try:
        send_verification_email.delay(to_email=user.email, raw_token=raw_verification_token)
    except Exception:
        # Same non-blocking pattern as transfer confirmation: registration
        # has already succeeded and committed, a queueing failure here
        # shouldn't fail the whole request.
        pass

    return user


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    try:
        await confirm_verification_token(db, payload.token)
    except EmailVerificationTokenInvalid:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    await db.commit()
    return None


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    # OAuth2PasswordRequestForm uses "username" as the field name; we treat it as email.
    user = await UserRepository(db).get_by_email(form_data.username)

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
