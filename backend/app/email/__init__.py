# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from app.email.backend import (
    ConsoleMailBackend,
    EmailMessage,
    MailBackend,
    SmtpMailBackend,
    get_mail_backend,
)

__all__ = [
    "ConsoleMailBackend",
    "EmailMessage",
    "MailBackend",
    "SmtpMailBackend",
    "get_mail_backend",
]
