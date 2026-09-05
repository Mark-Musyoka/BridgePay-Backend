from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.limiter import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.modules.accounts.repository import AccountRepository
from app.modules.audit.service import log_action
from app.modules.auth.schemas import (
    LogoutRequest,
    PasswordResetConfirmSchema,
    PasswordResetRequestSchema,
    RefreshRequest,
    Token,
    VerifyEmailRequest,
)
from app.modules.auth.service import (
    EmailVerificationTokenInvalid,
    PasswordResetTokenInvalid,
    RefreshTokenInvalid,
    RefreshTokenReused,
    confirm_password_reset,
    confirm_verification_token,
    issue_refresh_token,
    issue_verification_token,
    request_password_reset,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.modules.auth.tasks import send_password_reset_email, send_verification_email
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate, UserResponse

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
        country=payload.country,
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
@limiter.limit("10/minute")
async def verify_email(request: Request, payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    try:
        await confirm_verification_token(db, payload.token)
    except EmailVerificationTokenInvalid:
        await log_action(db, request=request, action="email_verification_failed")
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    await log_action(db, request=request, action="email_verified")
    await db.commit()
    return None


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Issues a fresh verification token for the logged-in user and queues a
    new (mocked) email. Requires auth rather than taking an email in the
    body — since login isn't gated on verification, a user who needs this
    can already log in, so there's no need for the user-enumeration
    precautions the password-reset-request flow needs.
    """
    if current_user.is_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already verified")

    raw_verification_token = await issue_verification_token(db, current_user.id)

    await log_action(db, request=request, action="verification_email_resent", user_id=current_user.id)
    await db.commit()

    try:
        send_verification_email.delay(to_email=current_user.email, raw_token=raw_verification_token)
    except Exception:
        pass

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
        await log_action(db, request=request, action="refresh_failed")
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    await log_action(db, request=request, action="token_refreshed")
    await db.commit()

    new_access_token = create_access_token(subject=user_id)
    return Token(access_token=new_access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def logout(request: Request, payload: LogoutRequest, db: AsyncSession = Depends(get_db)):
    await revoke_refresh_token(db, payload.refresh_token)
    # BUG FIX: logout previously had no audit trail at all, unlike every
    # other auth action (login, refresh, register, etc.) — added for
    # consistency, since "who logged out and when" is exactly the kind of
    # thing an audit log should cover.
    await log_action(db, request=request, action="logout")
    await db.commit()
    return None


@router.post("/password-reset-request", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def password_reset_request(
    request: Request, payload: PasswordResetRequestSchema, db: AsyncSession = Depends(get_db)
):
    raw_token = await request_password_reset(db, payload.email)

    await log_action(db, request=request, action="password_reset_requested", detail=payload.email)
    await db.commit()

    # Only queue the email if the user actually exists — but the HTTP
    # response is identical (204, no body) either way, so this endpoint
    # can't be used to discover which emails are registered.
    if raw_token is not None:
        try:
            send_password_reset_email.delay(to_email=payload.email, raw_token=raw_token)
        except Exception:
            pass

    return None


@router.post("/password-reset-confirm", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def password_reset_confirm(
    request: Request, payload: PasswordResetConfirmSchema, db: AsyncSession = Depends(get_db)
):
    try:
        await confirm_password_reset(db, payload.token, payload.new_password)
    except PasswordResetTokenInvalid:
        await log_action(db, request=request, action="password_reset_failed")
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    await log_action(db, request=request, action="password_reset_completed")
    await db.commit()
    return None
