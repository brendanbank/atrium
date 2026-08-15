# ADR 0003 — Secret-at-rest primitive (`app.host_sdk.crypto`)

Status: accepted, 2026-08-15. The `scope="user"` half is superseded by
[ADR 0004](0004-user-scope-secrets.md) — it does not arrive as a
parameter on this column type, and its keys are stored rather than
derived. Everything below about `scope="site"` stands.

## Context

Atrium owns `auth_tokens`, `service_accounts`, `auth_sessions` and the
password hashing that backs them, but it has never shipped a way to
store a **third-party** secret — an API key, a provider password, a
non-OAuth ingest token. Host apps that need one have had to make
cryptographic decisions themselves.

`atrium-pa` did, twice over: a per-purpose AES-256-GCM column type in
2026-04, then a full key-management stack on top of it (a
`KeyProvider` protocol with three implementations, a per-user KEK wrap
table, crypto-shredding, a Vault Transit backend, a blind-index HMAC
module). `banzai-anomalies` now needs per-provider LLM credentials on
its review surface, and without a platform answer it would write a
third.

Issue #225 asked whether atrium could lift PA's module. It cannot: PA's
current wire format binds `owner_user_id` into the AEAD's associated
data and refuses to decrypt anything older, and `FieldKey.encrypt`
routes through the whole provider stack. Lifting means taking all of
it. The thing atrium should own is the primitive underneath: a column
type that encrypts, and a key it encrypts under.

Two properties of the problem shaped the decision, and neither is
recoverable if we get it wrong in the first commit:

1. **There are two scopes of secret, not one.** A *site* secret is one
   the whole installation uses — an LLM API key has no "whose" about
   it. A *user* secret belongs to one person, must never be usable for
   another, and should die when they are deleted. PA shipped per-user
   first and bolted the site case on afterwards as a `system=True`
   flag, so today a single boolean switches both the key path and the
   wire format, and flipping it on a populated column corrupts the
   bytes.
2. **The wire format is the only irreversible part.** Everything else
   in a v1 — which KDF, how the key is configured, what the API looks
   like — can be changed later behind a version byte. The bytes
   already written cannot.

## Decision

### One column type, two scopes, `user` not implemented in v1

```python
EncryptedText(purpose="provider_credential.api_key", scope="site")
```

`scope` is `"site"` or `"user"`. v1 implements `site`. `scope="user"`
raises at construction time with a message naming the machinery it
implies — a request-scoped owner binding, defined behaviour outside a
request scope, AAD binding of the owner, a wrap record and shredding
semantics — so that it reads as unbuilt rather than as a string that
has not been typed yet. A test asserts the rejection fires: silently
falling back to `site` would ship a cross-user isolation break as a
bug.

**`user`, not `tenant`.** Atrium's existing prose uses "tenant" to mean
the installation (`api/account_deletion.py`, `api/signup.py`,
`services/signup.py`), and the RBAC model has no tenant entity — only
users and roles. `user` matches `owner_user_id` and matches the thing
that gets shredded.

### Headered wire format, from the first commit

```
ATR | version(1) | scope(1) | nonce(12) | ciphertext | tag(16)
 3B      0x01      0x01=site
```

The header is authenticated as AEAD associated data, so flipping the
scope byte on a stored blob fails the tag rather than silently
selecting a different key path.

A blob is therefore self-describing: a `user`-scope ciphertext can
never be read as a `site`-scope one, and the type does not have to
consult the column definition to know what it is holding. PA's history
is the argument for paying this up front — its original blobs are
prefix-less and start with a random nonce, so the later format needed a
magic bolted on, and needed four bytes rather than one because a
single version byte collides with a random nonce prefix at 1/256.
Written in the first commit, the discriminator costs five bytes a row
and nothing else.

**No byte-compatibility with `atrium-pa`.** Matching PA's bare
`nonce || ct || tag` would have made a future re-base of its two
`system=True` columns a config change instead of a re-encrypt. Two
columns is not worth constraining atrium's format permanently, and the
scope byte is incompatible with that shape anyway.

### Keys

- A dedicated `SECRET_ENCRYPTION_KEY` env var, 32 bytes hex. **Not**
  derived from `APP_SECRET_KEY` or `JWT_SECRET`: rotating a session
  secret must not destroy stored data, and the blast radius of a leaked
  signing key should not include every credential in the database.
- Per-column keys are HKDF-SHA256 derived from it, with the info string
  `"<scope>.<purpose>.<key_version>"`. `purpose` is what stops a
  ciphertext being moved between columns and still decrypting;
  `key_version` is what makes rotation possible later without a wire
  change.
- A dev-default constant plus rejection in `_prod_sanity`, matching how
  `APP_SECRET_KEY` and `JWT_SECRET` already fail closed. Considered and
  rejected: *unset raises at first use* (a deploy that boots fine and
  500s on the first credential read is worse than one that refuses to
  boot) and *auto-generate an ephemeral dev key* (dev databases become
  unreadable after every restart).

### Reads return a masked wrapper, not `str`

`process_result_value` returns a `MaskedSecret`; callers that need the
value call `.reveal()`.

This is the part that turns "the cleartext never crosses the API
boundary" from a convention into a mechanism. The convention alone
covers one exit and misses three that atrium owns, all of which take a
plain `str` and serialise it:

- `services.audit._json_safe` returns `str` unchanged on its first
  branch, so a credential-update diff lands in `audit_log` in
  cleartext, in a table with configurable retention;
- structlog binding, and SQLAlchemy's model repr in a traceback;
- Pydantic `from_attributes`, which picks the field up by default.

`MaskedSecret` deliberately does **not** subclass `str` — subclassing
would satisfy every one of those `isinstance` checks and leak anyway.
It renders as `***`, so the audit fallthrough and any stray f-string
produce a redaction rather than a secret, and a response model that
names the field fails loudly at serialisation instead of quietly
succeeding.

## Consequences

- Encrypted columns cannot be indexed, made unique, `ORDER BY`-ed or
  `LIKE`-matched. PA needed a blind-index HMAC module for that; atrium
  states it as unsupported rather than implying otherwise by silence.
- A database dump alone no longer restores an installation. The key
  becomes an operational artifact, and losing it means the credentials
  are unrecoverable — recovery is operators re-entering secrets.
- `purpose` binds a ciphertext to a column but not to a **row**. A
  DB-write attacker or a buggy import can move a blob between rows of
  the same column and the app will use it. A `TypeDecorator` has no row
  context at bind time, which is exactly why PA reached for ContextVars.
  Acceptable while only `site` scope exists — where the same secret is
  shared installation-wide anyway — and the reason `user` scope cannot
  be a later flag flip.
- Rotation is not automated. The documented procedure is to declare a
  second column at `key_version="v2"`, backfill, and drop the first.
- `cryptography` becomes a direct dependency. It was already present
  transitively via `pyjwt` / `webauthn`, which meant no declared floor
  for what is now a security-critical use.
- `atrium-pa` keeps its own implementation and is a documented superset,
  not a consumer. This does not collapse two implementations into one;
  it stops the count reaching three and gives the platform a blessed
  baseline.
