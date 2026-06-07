// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Visually-hidden, autofill-tagged username field for the 2FA page.
 *
 * The /2fa challenge page otherwise has only a one-time-code field. iOS
 * Password AutoFill (which 1Password uses on iOS) and desktop password
 * managers scope autofill to a specific account using the page's username
 * field. With none present, 1Password can match the *domain* but not the
 * *account* — so on the OTP page it opens the whole vault instead of
 * jumping to the matching login, and falls back to copying the code to the
 * clipboard rather than filling it inline.
 *
 * Carrying the signing-in email in an `autocomplete="username"` field gives
 * the autofill machinery the account context it needs. The field is kept in
 * the DOM (the sr-only pattern, not `display:none`) so the autofill
 * heuristics still see it, and `aria-hidden` keeps the decoy out of the
 * screen-reader tree.
 *
 * Renders nothing when the email is unknown (e.g. a hard reload of /2fa
 * where the login-page navigation state was lost) — the page degrades to
 * its previous behaviour rather than shipping an empty, unfillable field.
 */
export function AutofillUsernameField({ email }: { email?: string }) {
  if (!email) return null;
  return (
    <input
      type="text"
      name="username"
      autoComplete="username"
      value={email}
      readOnly
      tabIndex={-1}
      aria-hidden="true"
      style={{
        position: 'absolute',
        width: 1,
        height: 1,
        padding: 0,
        margin: -1,
        overflow: 'hidden',
        clip: 'rect(0, 0, 0, 0)',
        whiteSpace: 'nowrap',
        border: 0,
      }}
    />
  );
}
