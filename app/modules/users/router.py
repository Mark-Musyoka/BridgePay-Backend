from fastapi import APIRouter, Depends

from app.core.countries import COUNTRIES
from app.core.dependencies import get_current_user
from app.modules.users.models import User
from app.modules.users.schemas import CountryResponse, UserResponse

router = APIRouter(prefix="/users", tags=["users"])

# No /users prefix and no auth — the signup page needs this before a user
# exists at all, so it can't live under an authenticated /users/* route.
public_router = APIRouter(tags=["reference-data"])


@router.get("/me", response_model=UserResponse)
async def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@public_router.get("/countries", response_model=list[CountryResponse])
async def list_countries():
    return [CountryResponse(code=code, name=name) for code, name in COUNTRIES]
