from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in: int


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in: int


class MeResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str

    model_config = {'from_attributes': True}


class WebSocketSessionResponse(BaseModel):
    expires_in: int
