from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

from api_trafix.models.users import UserRole, UserStatus

Name = Annotated[str, StringConstraints(min_length=1, max_length=100)]
Username = Annotated[str, StringConstraints(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")]
Password = Annotated[str, StringConstraints(min_length=8, max_length=255)]


def _check_password_strength(value: str | None) -> str | None:
    if value is None:
        return value
    if not any(c.isupper() for c in value):
        raise ValueError("Password must contain an uppercase letter")
    if not any(c.islower() for c in value):
        raise ValueError("Password must contain a lowercase letter")
    if not any(c.isdigit() for c in value):
        raise ValueError("Password must contain a digit")
    return value


StrongPassword = Annotated[Password, AfterValidator(_check_password_strength)]


def _normalize_username(value: str | None) -> str | None:
    if value is None:
        return value
    return value.strip().lower()


def _reject_username_password_collision(model, username: str | None, password: str | None) -> None:
    if username and password and password.lower() == username:
        raise ValueError("Password must not be the same as the username")


class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name
    username: Username
    role: UserRole
    status: UserStatus

    _normalize_username = field_validator("username")(_normalize_username)


class UserCreate(UserBase):
    password: StrongPassword

    @model_validator(mode="after")
    def _username_not_in_password(self):
        _reject_username_password_collision(self, self.username, self.password)
        return self


class UserUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name | None = None
    username: Username | None = None
    password: StrongPassword | None = None
    role: UserRole | None = None
    status: UserStatus | None = None

    _normalize_username = field_validator("username")(_normalize_username)

    @model_validator(mode="after")
    def _username_not_in_password(self):
        _reject_username_password_collision(self, self.username, self.password)
        return self


class UserRead(UserBase):
    id: UUID
    last_login: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PasswordReset(BaseModel):
    password: StrongPassword


class UserPage(BaseModel):
    items: list[UserRead]
    total: int
    page: int
    page_size: int
    total_pages: int
