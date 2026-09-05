from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.countries import COUNTRIES
from app.core.dependencies import get_current_user
from app.core.limiter import limiter
from app.db.session import get_db
from app.modules.audit.service import log_action
from app.modules.users.models import User
from app.modules.users.schemas import (
    ChangePasswordRequest,
    CountryResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.modules.users.service import (
    EmailAlreadyTaken,
    IncorrectCurrentPassword,
    change_password,
    update_profile,
)

router = APIRouter(prefix="/users", tags=["users"])

# No /users prefix and no auth — the signup page needs this before a user
# exists at all, so it can't live under an authenticated /users/* route.
public_router = APIRouter(tags=["reference-data"])


@router.get("/me", response_model=UserResponse)
async def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_current_user(
    request: Request,
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        updated_user = await update_profile(
            db,
            user=current_user,
            full_name=payload.full_name,
            email=payload.email,
            country=payload.country,
        )
    except EmailAlreadyTaken as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await log_action(db, request=request, action="profile_updated", user_id=current_user.id)
    await db.commit()
    await db.refresh(updated_user)
    return updated_user


@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def change_current_user_password(
    request: Request,
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await change_password(
            db,
            user=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except IncorrectCurrentPassword:
        await log_action(db, request=request, action="change_password_failed", user_id=current_user.id)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    await log_action(db, request=request, action="password_changed", user_id=current_user.id)
    await db.commit()
    return None


@public_router.get("/countries", response_model=list[CountryResponse])
async def list_countries():
    return [CountryResponse(code=code, name=name) for code, name in COUNTRIES]
