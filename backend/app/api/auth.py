"""Auth routes. Business logic lives in app.auth; blocking work (PBKDF2, SQLite) runs in worker threads."""

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field

from app import auth
from app.auth import User, bearer, current_user
from app.hindsight import client as hindsight
from app.hindsight.client import HindsightError
from app.hindsight.preferences import load_profile
from app.schemas import MeResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class AuthResponse(BaseModel):
    token: str
    user_id: str
    username: str


def _session(user: User) -> AuthResponse:
    return AuthResponse(token=auth.create_session(user), user_id=user.id, username=user.username)


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: Credentials) -> AuthResponse:
    user = await run_in_threadpool(auth.create_user, body.username, body.password)
    if user is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username is already taken")
    session = await run_in_threadpool(_session, user)
    # Create the user's private, empty memory bank (reads of a missing bank would 404).
    await hindsight.ensure_bank(user.bank_id)
    return session


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, background: BackgroundTasks) -> AuthResponse:
    user = await run_in_threadpool(auth.authenticate, body.username, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    # Warm the bank cache without making the login wait for Hindsight.
    background.add_task(hindsight.ensure_bank, user.bank_id)
    return await run_in_threadpool(_session, user)


@router.post("/logout", status_code=204)
def logout(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if creds:
        auth.delete_session(creds.credentials)


async def _preferences(bank_id: str) -> list[str] | None:
    try:
        profile = await load_profile(bank_id)
    except HindsightError:
        return None
    return [p.preference for p in profile.preferences]


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(current_user)) -> MeResponse:
    prefs, memory_status = await asyncio.gather(_preferences(user.bank_id), hindsight.health(user.bank_id))
    return MeResponse(user_id=user.id, username=user.username, hindsight=memory_status, preferences=prefs)
