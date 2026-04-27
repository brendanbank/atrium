# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""SQLAlchemy models — import everything so Base.metadata is populated
before Alembic autogenerate and before any query runs."""

from app.models.auth import User, UserInvite
from app.models.auth_session import AuthSession
from app.models.email_otp import EmailOTPChallenge, UserEmailOTP
from app.models.email_outbox import EmailOutbox
from app.models.email_template import EmailTemplate
from app.models.email_verification import EmailVerification
from app.models.enums import EmailStatus, JobState, Language
from app.models.ops import AppSetting, AuditLog, EmailLog, Notification, ScheduledJob
from app.models.rbac import Permission, Role, role_permissions, user_roles
from app.models.reminder_rule import ReminderRule
from app.models.user_totp import UserTOTP
from app.models.webauthn import WebAuthnChallenge, WebAuthnCredential

__all__ = [
    "AppSetting",
    "AuditLog",
    "AuthSession",
    "EmailLog",
    "EmailOTPChallenge",
    "EmailOutbox",
    "EmailStatus",
    "EmailTemplate",
    "EmailVerification",
    "JobState",
    "Language",
    "Notification",
    "Permission",
    "ReminderRule",
    "Role",
    "ScheduledJob",
    "User",
    "UserEmailOTP",
    "UserInvite",
    "UserTOTP",
    "WebAuthnChallenge",
    "WebAuthnCredential",
    "role_permissions",
    "user_roles",
]
