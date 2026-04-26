from typing import Any

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, IntegerIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from app.auth.db import get_user_db
from app.logging import log
from app.models.auth import User
from app.settings import get_settings


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    """Handles hashing, password reset, email verification tokens.

    Secrets for reset + verify tokens come from settings; they're
    short-lived signed tokens separate from JWT access tokens.
    """

    @property
    def reset_password_token_secret(self) -> str:
        return get_settings().app_secret_key

    @property
    def verification_token_secret(self) -> str:
        return get_settings().app_secret_key

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        log.info("user.registered", user_id=user.id, email=user.email)

    async def on_after_login(
        self,
        user: User,
        request: Request | None = None,
        response=None,
    ) -> None:
        """Audit every successful login. Best-effort: we write with a
        fresh session so a failure here doesn't block the login itself."""
        try:
            from app.db import get_session_factory
            from app.services.audit import record

            async with get_session_factory()() as s:
                await record(
                    s,
                    actor_user_id=user.id,
                    entity="user",
                    entity_id=user.id,
                    action="login",
                    diff=None,
                )
                await s.commit()
        except Exception as exc:
            log.warning("audit.login_write_failed", error=str(exc))

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        # Only the fact of the request is logged — never the token
        # itself. Anyone with read access to application logs would
        # otherwise be able to hijack the account. If SMTP is
        # misconfigured and a reset is stuck, regenerate via the
        # admin UI rather than plucking the token from logs.
        log.info(
            "user.password_reset_requested",
            user_id=user.id,
            email=user.email,
        )
        # Deliver the reset link. Wrapped so a broken SMTP config can't
        # surface as a 500 on /auth/forgot-password (which is called
        # unauthenticated and would leak the failure).
        from app.db import get_session_factory
        from app.email.sender import send_and_log
        from app.settings import get_settings

        reset_url = (
            f"{get_settings().app_base_url.rstrip('/')}/reset-password?token={token}"
        )
        try:
            async with get_session_factory()() as s:
                await send_and_log(
                    s,
                    template="password_reset",
                    to=[user.email],
                    context={
                        "user": user,
                        "reset_url": reset_url,
                        "recipient": {
                            "email": user.email.lower(),
                            "full_name": user.full_name or "",
                        },
                    },
                )
                await s.commit()
        except Exception as exc:
            log.warning(
                "password_reset.email_failed",
                user_id=user.id,
                email=user.email,
                error=str(exc),
            )

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        # Token deliberately omitted from the log — see the note in
        # on_after_forgot_password.
        log.info(
            "user.verify_requested",
            user_id=user.id,
            email=user.email,
        )

    async def validate_password(self, password: str, user: Any) -> None:
        if len(password) < 8:
            from fastapi_users.exceptions import InvalidPasswordException
            raise InvalidPasswordException(reason="password must be at least 8 characters")


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
):
    yield UserManager(user_db)
