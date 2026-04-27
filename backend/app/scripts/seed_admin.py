# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Create or reset the bootstrap admin account.

No public registration — this script is the only way to get the first
user into a fresh environment. Idempotent: re-running with the same
email resets the password.

Usage:
  python -m app.scripts.seed_admin \
      --email me@example.com \
      --password s3cret \
      --full-name "Your Name"

Pass ``--super-admin`` to also grant the ``super_admin`` role (needed
for user.impersonate and any other super-only permission your host app
adds). Atrium grants super_admin automatically to whichever user the
init migration designates; a re-seed after migrations needs the flag.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from fastapi_users.password import PasswordHelper
from sqlalchemy import delete, select

from app.auth.rbac import assign_role
from app.db import get_engine, get_session_factory
from app.logging import configure_logging, log
from app.models.auth import User
from app.models.email_otp import UserEmailOTP
from app.models.enums import Language
from app.models.user_totp import UserTOTP
from app.settings import get_settings, is_dev_default_password

ADMIN_ROLE_CODE = "admin"


async def _run(
    email: str,
    password: str,
    full_name: str,
    *,
    super_admin: bool = False,
    totp_secret: str | None = None,
    email_otp_confirmed: bool = False,
) -> int:
    if len(password) < 8:
        print("error: password must be at least 8 characters", file=sys.stderr)
        return 2

    if (
        get_settings().environment == "prod"
        and is_dev_default_password(password)
    ):
        print(
            "error: refusing to seed a dev-default password in prod — "
            "pick a new one",
            file=sys.stderr,
        )
        return 2

    helper = PasswordHelper()
    hashed = helper.hash(password)

    factory = get_session_factory()
    try:
        async with factory() as session:
            existing = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()

            if existing is None:
                user = User(
                    email=email,
                    hashed_password=hashed,
                    is_active=True,
                    is_verified=True,
                    full_name=full_name,
                    phone=None,
                    preferred_language=Language.EN.value,
                )
                session.add(user)
                await session.flush()
                user_id = user.id
                action = "created"
            else:
                existing.hashed_password = hashed
                existing.full_name = full_name
                existing.is_active = True
                existing.is_verified = True
                user_id = existing.id
                action = "reset"

            await assign_role(session, user_id=user_id, role_code=ADMIN_ROLE_CODE)
            if super_admin:
                await assign_role(session, user_id=user_id, role_code="super_admin")

            if totp_secret is not None:
                await session.execute(
                    delete(UserTOTP).where(UserTOTP.user_id == user_id)
                )
                session.add(
                    UserTOTP(
                        user_id=user_id,
                        secret=totp_secret,
                        confirmed_at=datetime.utcnow(),
                    )
                )
            if email_otp_confirmed:
                await session.execute(
                    delete(UserEmailOTP).where(UserEmailOTP.user_id == user_id)
                )
                session.add(
                    UserEmailOTP(
                        user_id=user_id,
                        confirmed_at=datetime.utcnow(),
                    )
                )

            await session.commit()
    finally:
        await get_engine().dispose()

    log.info("seed_admin.done", email=email, action=action)
    print(f"admin {action}: {email}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed (or reset) an admin account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument(
        "--super-admin",
        action="store_true",
        help="Also grant the super_admin role (impersonation + privilege mgmt).",
    )
    parser.add_argument(
        "--totp-secret",
        default=None,
        help=(
            "Pre-enroll TOTP with this base32 secret (for smoke/e2e). "
            "The runner then generates codes against the same secret."
        ),
    )
    parser.add_argument(
        "--email-otp",
        action="store_true",
        help=(
            "Pre-enroll email OTP (confirmed). Used by the email-OTP "
            "e2e test so Playwright can log in via the email challenge."
        ),
    )
    args = parser.parse_args()

    configure_logging()
    code = asyncio.run(
        _run(
            args.email,
            args.password,
            args.full_name,
            super_admin=args.super_admin,
            totp_secret=args.totp_secret,
            email_otp_confirmed=args.email_otp,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
