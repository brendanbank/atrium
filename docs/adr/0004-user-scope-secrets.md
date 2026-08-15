# ADR 0004 — User-scope secrets (`UserSecret`, `user_secret_keys`)

Status: accepted, 2026-08-15

Supersedes the "not built" half of
[ADR 0003](0003-secret-at-rest.md). Site scope is unchanged.

## Context

0.27.0 shipped `scope="site"` and declared `scope="user"` as the second
half of the dimension, deliberately unbuilt. The rejection message
described what it would need: *"a request-scoped owner binding, defined
behaviour outside a request scope, the owner bound into the AEAD, and a
key-wrap record with shredding semantics."*

Issue #227 (`atrium-ddns`) showed that description is wrong in one
important way. That host is multi-tenant, and its hot path is a home
router calling `GET /nic/update` over HTTP Basic — authenticated as a
*device*, with no atrium session, no cookie, and no PAT (atrium's PAT
middleware only matches `Bearer`). The device's own secret is read
*during* that authentication, before any identity exists at all. Worker
jobs have no request either.

So "the owner is the authenticated user" is unusable. **The owner has
to come from the row being decrypted.**

Validating that issue turned up two further constraints that decide the
design:

1. **A derived key cannot be shredded.** #227 assumed per-user keys
   would be HKDF-derived from the master, since `key_version` is
   already in the info string. But a key computable from the master is
   computable forever — delete the user, keep the master, and every
   blob they wrote is still readable. That is precisely the property
   the issue rejects the `scope="site"` workaround over.
   `atrium-pa` walked into this: its `DerivedKeyProvider` documents
   that the KEK "is recomputable from the root + user_id alone" and
   that shredded-user checks "happen at the request-scope boundary".
   That is access control at the door, not crypto-shredding.
2. **A `TypeDecorator` cannot be row-aware.** `process_bind_param` and
   `process_result_value` receive a value and a dialect — no instance,
   no row, in either direction. `owner_attr=` cannot be a parameter on
   `EncryptedText`. This is the same wall `atrium-pa` hit, and its
   ContextVar workaround is what produced the request-bound design in
   the first place.

## Decision

### The key is random, stored, and wrapped — never derived

New table `user_secret_keys`: one row per user, `user_id` as the
primary key, `wrapped_key` holding 32 random bytes encrypted under a
master-derived wrapping key with the user id in the AEAD's associated
data.

`ON DELETE CASCADE` on `users.id` **is** the shredding mechanism. When
the user row goes, the only copy of that key goes with it, and every
ciphertext ever written for them is unreadable from then on — including
in a backup taken before the delete, which is the case a policy check
cannot cover.

Per-column keys are HKDF-derived *from the user's key* with
`"user.<purpose>.<key_version>"`, so `purpose` keeps binding a
ciphertext to a column within the user's own data.

### Shredding happens at hard delete, and that is not a detail

`register_pre_user_delete` — nominated by #225 as the seam — fires at
`admin_users.py` and the `account_hard_delete` job, both immediately
before `session.delete(user)`. `soft_delete_user` does not run hooks,
and must not shred: atrium supports reinstating an account during
`auth.delete_grace_days`, and an account reinstated without its
credentials is worse than one that stays deleted. So the promise is
"destroyed when the hard delete runs", after the grace window. Hosts
that need it sooner call `shred_user_key()` themselves.

The `ON DELETE CASCADE` means the key cannot outlive the account even
if a future call path forgets to shred explicitly.

### The declaration is a descriptor beside a raw column

```python
class Device(HostBase):
    user_id: Mapped[int] = mapped_column(HostForeignKey("users.id"))
    secret_ct: Mapped[bytes | None] = mapped_column(SecretBlob(), nullable=True)
    secret = UserSecret(
        purpose="device.secret", owner_attr="user_id", column="secret_ct"
    )
```

Two declarations, because the crypto needs the row and only a
descriptor can see it. `SecretBlob` is a plain `LargeBinary` (widening
to `MEDIUMBLOB` on MySQL) that does no crypto and does not pretend to.
`scope="site"` keeps the `TypeDecorator` path untouched;
`EncryptedText(scope="user")` still raises, but now points at this
mechanism rather than at a milestone.

Writes are held as plaintext on the instance and encrypted in a
`before_flush` hook, so assigning the secret before the owner id — the
order keyword arguments happen to be written in — is not a
cryptographic decision.

### Unlocking is explicit, and scoped to the session

```python
await unlock_user_secrets(session, device.user_id)   # one await, no principal
device.secret.reveal()
```

Unwrapping is a database read. Every place it would be convenient to
hide one — a type hook, a bare attribute access — is a **sync** call
site in an async-only codebase, and some of them (`load` events) fire
mid-result-iteration, where a nested query on the same MySQL connection
is its own failure mode. So the read is explicit and up front; touching
the attribute without it raises `SecretLockedError` naming the call to
make.

The unwrapped key lives in `session.info` and dies with the session.
There is deliberately no process-global cache: a shred has to bite
immediately, and `_derive_key`'s `lru_cache` is the wrong shape for
per-user material anyway — 64 entries thrash past 64 users, and
process-global key bytes with no eviction is a weaker posture than the
request-scoped cache `atrium-pa` uses, which a no-request design has no
boundary to hang off.

## Consequences

- Atrium now has a secret-bearing table and a migration
  (`0012_user_secret_keys`). ADR 0003's "no atrium table is needed"
  held only while keys were derived.
- Losing `SECRET_ENCRYPTION_KEY` now also loses every user key, since
  the wrap is under it. Same backup rule, larger blast radius.
- Cross-row portability, listed in ADR 0003 as an accepted limitation
  of site scope, is closed for user scope: the owner is in the AAD, so
  a blob moved to another user's row fails the tag.
- A host must know the owner before reading — one extra `await` after
  fetching the row. For `atrium-ddns` that is exactly where it already
  is: the device row carries `user_id`, so authentication reads the row
  first, unlocks, then verifies the secret.
- Still not built: Vault / KMS backends, blind-index search, automated
  rotation. The dual-column `key_version` procedure from ADR 0003
  remains the rotation path for both scopes.
