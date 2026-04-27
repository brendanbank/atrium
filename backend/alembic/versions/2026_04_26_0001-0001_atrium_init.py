# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Atrium initial schema.

Revision ID: 0001_atrium_init
Revises:
Create Date: 2026-04-26

Single migration that establishes the full Atrium platform schema:
users + auth (password, sessions, TOTP, email OTP, WebAuthn), invites,
RBAC (permissions, roles, junctions), audit log, in-app notifications,
email templates + reminder rules, scheduled jobs queue, app settings.

Seeds the system roles (admin / super_admin / user), the atrium-relevant
permission set, and a minimal default email-template trio (invite,
password reset, admin password-reset notice).
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_atrium_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- core: users ------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(1024), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("preferred_language", sa.String(5), nullable=False, server_default="en"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- invites ---------------------------------------------------------
    op.create_table(
        "user_invites",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        # RBAC role codes granted on accept (e.g. ["admin", "user"]).
        sa.Column("role_codes", sa.JSON, nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column(
            "invited_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("accepted_at", sa.DateTime, nullable=True),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_user_invites_token", "user_invites", ["token"], unique=True)
    op.create_index("ix_user_invites_email", "user_invites", ["email"])

    # ---- auth sessions (DB-backed JWT) ----------------------------------
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("user_agent", sa.String(200), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("totp_passed", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_auth_sessions_session_id", "auth_sessions", ["session_id"], unique=True
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_revoked_at", "auth_sessions", ["revoked_at"])

    # ---- TOTP ------------------------------------------------------------
    op.create_table(
        "user_totp",
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("secret", sa.String(64), nullable=False),
        sa.Column("confirmed_at", sa.DateTime, nullable=True),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ---- Email OTP -------------------------------------------------------
    op.create_table(
        "user_email_otp",
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("confirmed_at", sa.DateTime, nullable=True),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "email_otp_challenges",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_email_otp_challenges_user_id", "email_otp_challenges", ["user_id"]
    )
    op.create_index(
        "ix_email_otp_challenges_expires_at", "email_otp_challenges", ["expires_at"]
    )

    # ---- WebAuthn --------------------------------------------------------
    op.create_table(
        "user_webauthn_credentials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_id", sa.String(512), nullable=False),
        sa.Column("public_key", sa.LargeBinary, nullable=False),
        sa.Column("sign_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("transports", sa.String(64), nullable=True),
        sa.Column("last_used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_user_webauthn_credentials_user_id",
        "user_webauthn_credentials",
        ["user_id"],
    )
    op.create_index(
        "ix_user_webauthn_credentials_credential_id",
        "user_webauthn_credentials",
        ["credential_id"],
        unique=True,
    )

    op.create_table(
        "webauthn_challenges",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("challenge", sa.LargeBinary, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_webauthn_challenges_user_id", "webauthn_challenges", ["user_id"])
    op.create_index(
        "ix_webauthn_challenges_expires_at", "webauthn_challenges", ["expires_at"]
    )

    # ---- RBAC ------------------------------------------------------------
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(100), primary_key=True),
        sa.Column("description", sa.String(500), nullable=True),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_roles_code", "roles", ["code"], unique=True)

    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            sa.Integer,
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission_code",
            sa.String(100),
            sa.ForeignKey("permissions.code", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            sa.Integer,
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # ---- ops: notifications, scheduled jobs, email log, audit, settings -
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("read_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        # entity_type + entity_id let host apps attribute a job to a
        # domain row without a hard FK. Either both null or both set.
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.BigInteger, nullable=True),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("run_at", sa.DateTime, nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_scheduled_jobs_entity_type", "scheduled_jobs", ["entity_type"])
    op.create_index("ix_scheduled_jobs_entity_id", "scheduled_jobs", ["entity_id"])
    op.create_index("ix_scheduled_jobs_job_type", "scheduled_jobs", ["job_type"])
    op.create_index("ix_scheduled_jobs_run_at", "scheduled_jobs", ["run_at"])
    op.create_index("ix_scheduled_jobs_state", "scheduled_jobs", ["state"])

    op.create_table(
        "email_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.BigInteger, nullable=True),
        sa.Column("to_addr", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("template", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_id", sa.String(200), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_email_log_entity_type", "email_log", ["entity_type"])
    op.create_index("ix_email_log_entity_id", "email_log", ["entity_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "actor_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "impersonator_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.BigInteger, nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("diff", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index(
        "ix_audit_log_impersonator_user_id", "audit_log", ["impersonator_user_id"]
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity"])
    op.create_index("ix_audit_log_entity_id", "audit_log", ["entity_id"])

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.JSON, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # ---- email templates + reminder rules -------------------------------
    op.create_table(
        "email_templates",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body_html", sa.Text, nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    op.create_table(
        "reminder_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "template_key",
            sa.String(100),
            sa.ForeignKey("email_templates.key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("anchor", sa.String(50), nullable=False),
        sa.Column("days_offset", sa.Integer, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # ---- seed: permissions ----------------------------------------------
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("code", sa.String),
            sa.column("description", sa.String),
        ),
        [
            {"code": "user.manage", "description": "List, create, update, delete users + invites."},
            {"code": "user.impersonate", "description": "Switch into another user's session."},
            {"code": "user.totp.reset", "description": "Reset another user's 2FA enrolment."},
            {"code": "role.manage", "description": "Create, edit, delete RBAC roles + their permissions."},
            {"code": "audit.read", "description": "Read the audit log."},
            {"code": "reminder_rule.manage", "description": "Create, edit, delete reminder rules."},
            {"code": "email_template.manage", "description": "Edit email templates."},
            {"code": "app_setting.manage", "description": "Edit runtime app settings."},
        ],
    )

    # ---- seed: roles -----------------------------------------------------
    op.bulk_insert(
        sa.table(
            "roles",
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("is_system", sa.Boolean),
        ),
        [
            {"code": "super_admin", "name": "Super admin", "is_system": True},
            {"code": "admin", "name": "Admin", "is_system": True},
            {"code": "user", "name": "User", "is_system": True},
        ],
    )

    # super_admin → every permission (including user.impersonate).
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_code)
        SELECT r.id, p.code FROM roles r CROSS JOIN permissions p
        WHERE r.code = 'super_admin'
        """
    )
    # admin → every permission except user.impersonate. The privilege-
    # escalation guard in admin_users.update prevents an admin from
    # self-promoting to super_admin.
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_code)
        SELECT r.id, p.code FROM roles r CROSS JOIN permissions p
        WHERE r.code = 'admin' AND p.code != 'user.impersonate'
        """
    )
    # user → no permissions. Host apps grant their own.

    # ---- seed: default email templates ----------------------------------
    op.bulk_insert(
        sa.table(
            "email_templates",
            sa.column("key", sa.String),
            sa.column("subject", sa.String),
            sa.column("body_html", sa.Text),
            sa.column("description", sa.String),
        ),
        [
            {
                "key": "invite",
                "subject": "You're invited to {{ app_name | default('Atrium') }}",
                "body_html": (
                    "<p>Hello,</p>"
                    "<p>{{ invited_by_name }} has invited you to join "
                    "{{ app_name | default('Atrium') }}.</p>"
                    "<p><a href=\"{{ accept_url }}\">Accept the invite</a> "
                    "and set your password.</p>"
                    "<p>The link expires on {{ expires_on }}.</p>"
                ),
                "description": "Sent when an admin invites a new user.",
            },
            {
                "key": "password_reset",
                "subject": "Reset your password",
                "body_html": (
                    "<p>Hello {{ recipient.full_name }},</p>"
                    "<p>You requested a password reset. "
                    "<a href=\"{{ reset_url }}\">Click here to set a new password</a>.</p>"
                    "<p>If you didn't request this, you can ignore this email.</p>"
                ),
                "description": "Self-service password reset link.",
            },
            {
                "key": "admin_password_reset_notice",
                "subject": "An admin reset your password",
                "body_html": (
                    "<p>Hello {{ recipient.full_name }},</p>"
                    "<p>{{ admin.full_name }} ({{ admin.email }}) just triggered a "
                    "password reset for your account. A separate email contains the "
                    "reset link.</p>"
                    "<p>If you didn't expect this, contact your administrator.</p>"
                ),
                "description": "Heads-up sent when an admin triggers a password reset on someone else's account.",
            },
            {
                "key": "email_otp_code",
                "subject": "Your sign-in code",
                "body_html": (
                    "<p>Hello {{ user_name }},</p>"
                    "<p>Your sign-in code is <strong>{{ code }}</strong>.</p>"
                    "<p>It expires in 10 minutes. If you didn't try to sign in, "
                    "you can ignore this email.</p>"
                ),
                "description": "Six-digit second-factor code delivered when a user picks email OTP at the /2fa challenge.",
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("reminder_rules")
    op.drop_table("email_templates")
    op.drop_table("app_settings")
    op.drop_index("ix_audit_log_entity_id", table_name="audit_log")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_index("ix_audit_log_impersonator_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_user_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_email_log_entity_id", table_name="email_log")
    op.drop_index("ix_email_log_entity_type", table_name="email_log")
    op.drop_table("email_log")
    op.drop_index("ix_scheduled_jobs_state", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_run_at", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_job_type", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_entity_id", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_entity_type", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_index("ix_roles_code", table_name="roles")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_index("ix_webauthn_challenges_expires_at", table_name="webauthn_challenges")
    op.drop_index("ix_webauthn_challenges_user_id", table_name="webauthn_challenges")
    op.drop_table("webauthn_challenges")
    op.drop_index(
        "ix_user_webauthn_credentials_credential_id",
        table_name="user_webauthn_credentials",
    )
    op.drop_index(
        "ix_user_webauthn_credentials_user_id",
        table_name="user_webauthn_credentials",
    )
    op.drop_table("user_webauthn_credentials")
    op.drop_index(
        "ix_email_otp_challenges_expires_at", table_name="email_otp_challenges"
    )
    op.drop_index("ix_email_otp_challenges_user_id", table_name="email_otp_challenges")
    op.drop_table("email_otp_challenges")
    op.drop_table("user_email_otp")
    op.drop_table("user_totp")
    op.drop_index("ix_auth_sessions_revoked_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_session_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_user_invites_email", table_name="user_invites")
    op.drop_index("ix_user_invites_token", table_name="user_invites")
    op.drop_table("user_invites")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
