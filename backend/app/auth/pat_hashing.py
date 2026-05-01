# Copyright (c) 2026 Brendan Bank
# SPDX-License-Identifier: BSD-2-Clause

"""Argon2id hashing for personal access tokens.

argon2id is the right primitive: deliberately slow (defeats brute
force), memory-hard (defeats GPUs), parameter-tunable. The defaults
here (time_cost=2, memory_cost=64 MiB, parallelism=2) target
~50-150 ms per verify on modern hardware — fast enough for one
verify per request, slow enough that an attacker who exfiltrates
the DB can't iterate the keyspace.

The lookup-prefix index keeps verify count to (almost always) 1
per request. PATAuthMiddleware does ``scalars().all() +
verify_token-each`` to handle the rare prefix collision correctly.
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError

# Module-global so the parameters and the small per-process state
# (compiled bindings, RNG) stay warm across requests.
_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=2,
)


def hash_token(token: str) -> str:
    """Hash a freshly-minted token. Returns the argon2 encoded form
    (algorithm + parameters + salt + digest, ~96 chars)."""
    return _hasher.hash(token)


def verify_token(token: str, encoded_hash: str) -> bool:
    """Constant-time-ish verify. Returns False on any kind of
    mismatch or malformed hash; never raises.

    ``argon2-cffi`` raises ``VerifyMismatchError`` for plain wrong-
    password and ``InvalidHashError`` / ``Argon2Error`` for malformed
    inputs. We treat all of them the same way: ``False``. The caller
    is the auth middleware, and the only signal it acts on is
    "verified or not".
    """
    try:
        return _hasher.verify(encoded_hash, token)
    except VerifyMismatchError:
        return False
    except Argon2Error:
        return False
    except Exception:
        # Defensive: a bug-shaped error in the argon2 binding must
        # not turn an unauthenticated request into a 500.
        return False
