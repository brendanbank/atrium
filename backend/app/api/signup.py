"""Self-serve signup + verify-email endpoints.

The register route is rate-limited via ``AuthRateLimitMiddleware``
(see ``services.rate_limit.AUTH_LIMITS``). When ``auth.allow_signup``
is False the route returns 404 — same convention as
``/users/me/delete`` when ``allow_self_delete`` is off — so a tenant
that hasn't opted in doesn't broadcast the route's existence.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.services.signup import (
    EmailAlreadyRegistered,
    InvalidEmail,
    SignupDisabled,
    consume_verification,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    # Pydantic enforces only the absolute floor here — the live policy
    # (configurable per tenant via app_settings) runs inside
    # ``register_user`` and produces the user-facing error string.
    password: str = Field(min_length=1, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default="en", max_length=5)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


@router.post("/register", status_code=status.HTTP_204_NO_CONTENT)
async def register(
    payload: RegisterRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> Response:
    response.headers["Cache-Control"] = "no-store"
    try:
        await register_user(
            session,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            language=payload.language or "en",
        )
    except SignupDisabled as exc:
        # 404 rather than 403 — matches the /users/me/delete pattern so
        # the route's existence isn't revealed when the operator hasn't
        # opted in to self-serve signup.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account with this email already exists",
        ) from exc
    except InvalidEmail as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    await session.commit()
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(
    payload: VerifyEmailRequest,
    session: AsyncSession = Depends(get_session),
) -> Response:
    user = await consume_verification(session, token=payload.token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="verification link is invalid or expired",
        )
    await session.commit()
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "no-store"},
    )
