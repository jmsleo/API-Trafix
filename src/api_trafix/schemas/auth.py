from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from api_trafix.schemas.user import Username

LoginPassword = Annotated[str, StringConstraints(min_length=1, max_length=255)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: Username
    password: LoginPassword


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str
    access_token: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
