# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Leaf module: ``Principal`` dataclass + the request-scope sentinel.

A ``Principal`` is the per-request answer to "who is making this
call and what can they do". It uniformly covers two auth methods:

- **password (cookie-authed)** — the user logged in interactively.
  ``permissions`` is the user's full effective permission set.
- **pat / service_account_pat** — the user authenticated via a
  Personal Access Token. ``permissions`` is the *intersection* of
  the token's stored scopes and the user's current permissions
  (computed in ``PATAuthMiddleware``), so a demoted user's tokens
  silently lose the matching scopes the next time they're used.

Why a side-channel through ``request.scope[SCOPE_KEY]`` rather than
threading it through fastapi-users? The cookie-auth chain
(``current_user`` + ``auth_sessions.totp_passed`` gate) is purpose-
built for cookie sessions. PATs are a parallel auth method that
doesn't have a cookie session at all. Forcing them through the
same dep chain would either duplicate the gate logic or paper over
it; instead the PAT middleware short-circuits and pre-populates
the slot, and the resolver dep reads from it before falling back
to cookie auth.

This module is intentionally a **leaf** under ``app.auth.*`` —
``users.py`` and ``rbac.py`` import from here, never the reverse.
The resolver dep (``current_principal``) lives in ``rbac.py``
alongside ``require_perm`` because they're tightly coupled and
keeping them in one place prevents the cycle (CodeQL alerts
#42-#46 from PR #113).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.models.auth import User

AuthMethod = Literal["password", "pat", "service_account_pat"]


@dataclass(frozen=True)
class Principal:
    """The answer to "who is calling and what can they do" for one
    request. Constructed once per request (or short-circuited from
    the PAT middleware's slot) and threaded through ``require_perm``.

    ``user`` is always present. ``permissions`` is already
    *effective* — for PATs it's the scope ∩ user-permissions
    intersection, not the raw stored scopes. ``token_id`` is set
    only for PAT requests; ``auth_session_id`` is set only for
    cookie requests (and even then it's optional — populated when
    the resolver decoded the cookie's ``sid``).
    """

    user: User
    permissions: frozenset[str]
    auth_method: AuthMethod
    token_id: int | None = None
    auth_session_id: str | None = None


# Sentinel key for the request scope slot that ``PATAuthMiddleware``
# populates and ``current_principal`` reads back. Using ``request.scope``
# (the ASGI dict) rather than ``request.state`` keeps PAT principal
# objects out of the broader Starlette-state surface and ensures clean
# isolation between requests handled by the same worker.
SCOPE_KEY = "atrium_principal"
