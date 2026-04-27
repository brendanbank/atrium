# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

from enum import StrEnum


class JobState(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EmailStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class Language(StrEnum):
    EN = "en"
    NL = "nl"
