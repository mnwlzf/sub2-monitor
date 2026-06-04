from pydantic import BaseModel, Field


class CsrfResponse(BaseModel):
    csrf_token: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: int
    username: str


class SessionResponse(BaseModel):
    user: UserResponse
    csrf_token: str

