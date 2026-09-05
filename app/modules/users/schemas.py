import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.countries import VALID_COUNTRY_CODES


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2 code, e.g. 'KE'")

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: str) -> str:
        v = v.upper()
        if v not in VALID_COUNTRY_CODES:
            raise ValueError(f"'{v}' is not a recognized ISO 3166-1 alpha-2 country code")
        return v


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    is_verified: bool
    country: str | None
    created_at: datetime


class UpdateProfileRequest(BaseModel):
    """All fields optional — only what's provided gets updated."""
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in VALID_COUNTRY_CODES:
            raise ValueError(f"'{v}' is not a recognized ISO 3166-1 alpha-2 country code")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class CountryResponse(BaseModel):
    code: str
    name: str
