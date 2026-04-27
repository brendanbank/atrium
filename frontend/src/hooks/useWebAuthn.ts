// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { ME_QUERY_KEY } from './useAuth';
import { TOTP_STATE_KEY } from './useTOTP';

export interface WebAuthnCredential {
  id: number;
  label: string;
  transports: string | null;
  last_used_at: string | null;
  created_at: string;
}

/**
 * The ``navigator.credentials.create/get`` APIs want raw buffers for
 * the ``challenge``, credential ``id``, ``user.id``, and (during
 * authentication) the entries in ``allowCredentials``. The backend
 * serves them as base64url strings via py_webauthn's
 * ``options_to_json``. These helpers do the round-trip — no extra
 * dependency needed.
 */
function b64urlToBuffer(s: string): ArrayBuffer {
  const padded = s + '='.repeat((4 - (s.length % 4)) % 4);
  const bin = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
  const buf = new ArrayBuffer(bin.length);
  const out = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return buf;
}

function bufferToB64url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export const WEBAUTHN_CREDENTIALS_KEY = ['auth', 'webauthn', 'credentials'] as const;

// ---- Server options shape ------------------------------------------
//
// py_webauthn's ``options_to_json`` emits a dict with base64url strings
// where raw buffers would normally sit. We don't validate every field;
// the browser's WebAuthn API will reject malformed input for us. These
// types name just the members we read so the mapping logic below isn't
// forced to use ``any``.

interface CredentialDescriptorJSON {
  id: string;
  type: 'public-key';
  transports?: AuthenticatorTransport[];
}

interface RegistrationOptionsJSON {
  challenge: string;
  rp: { id: string; name: string };
  user: { id: string; name: string; displayName: string };
  pubKeyCredParams: Array<{ alg: number; type: 'public-key' }>;
  timeout?: number;
  attestation?: AttestationConveyancePreference;
  authenticatorSelection?: AuthenticatorSelectionCriteria;
  excludeCredentials?: CredentialDescriptorJSON[];
}

interface AuthenticationOptionsJSON {
  challenge: string;
  rpId: string;
  timeout?: number;
  userVerification?: UserVerificationRequirement;
  allowCredentials?: CredentialDescriptorJSON[];
}

export function useWebAuthnCredentials() {
  return useQuery({
    queryKey: WEBAUTHN_CREDENTIALS_KEY,
    queryFn: async () =>
      (await api.get<WebAuthnCredential[]>('/auth/webauthn/credentials')).data,
  });
}

/** Drive the full registration ceremony in one call: ask the backend
 * for options, invoke ``navigator.credentials.create``, POST the
 * attestation back. Returns when the credential row has landed. */
export function useWebAuthnRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (label: string) => {
      if (!('credentials' in navigator) || !navigator.credentials?.create) {
        throw new Error('WebAuthn not supported in this browser');
      }
      const { data: begin } = await api.post<{ options: RegistrationOptionsJSON }>(
        '/auth/webauthn/register/begin',
      );
      // Rebuild the options with real buffers where the server sent
      // base64url strings.
      const options = begin.options;
      const publicKey: CredentialCreationOptions['publicKey'] = {
        ...options,
        challenge: b64urlToBuffer(options.challenge),
        user: {
          ...options.user,
          id: b64urlToBuffer(options.user.id),
        },
        excludeCredentials: (options.excludeCredentials ?? []).map((c) => ({
          ...c,
          id: b64urlToBuffer(c.id),
        })),
      };

      const cred = (await navigator.credentials.create({
        publicKey,
      })) as PublicKeyCredential | null;
      if (!cred) throw new Error('registration cancelled');

      const attestation = cred.response as AuthenticatorAttestationResponse;
      const body = {
        label,
        credential: {
          id: cred.id,
          rawId: bufferToB64url(cred.rawId),
          type: cred.type,
          response: {
            clientDataJSON: bufferToB64url(attestation.clientDataJSON),
            attestationObject: bufferToB64url(attestation.attestationObject),
            transports:
              typeof attestation.getTransports === 'function'
                ? attestation.getTransports()
                : undefined,
          },
          clientExtensionResults: cred.getClientExtensionResults(),
          authenticatorAttachment:
            (cred as PublicKeyCredential & {
              authenticatorAttachment?: AuthenticatorAttachment;
            }).authenticatorAttachment ?? undefined,
        },
      };

      await api.post('/auth/webauthn/register/finish', body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: WEBAUTHN_CREDENTIALS_KEY });
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });
}

/** Drive the full authentication ceremony. */
export function useWebAuthnAuthenticate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      if (!('credentials' in navigator) || !navigator.credentials?.get) {
        throw new Error('WebAuthn not supported in this browser');
      }
      const { data: begin } = await api.post<{ options: AuthenticationOptionsJSON }>(
        '/auth/webauthn/authenticate/begin',
      );
      const options = begin.options;
      const publicKey: CredentialRequestOptions['publicKey'] = {
        ...options,
        challenge: b64urlToBuffer(options.challenge),
        allowCredentials: (options.allowCredentials ?? []).map((c) => ({
          ...c,
          id: b64urlToBuffer(c.id),
        })),
      };

      const cred = (await navigator.credentials.get({
        publicKey,
      })) as PublicKeyCredential | null;
      if (!cred) throw new Error('authentication cancelled');

      const assertion = cred.response as AuthenticatorAssertionResponse;
      const body = {
        credential: {
          id: cred.id,
          rawId: bufferToB64url(cred.rawId),
          type: cred.type,
          response: {
            clientDataJSON: bufferToB64url(assertion.clientDataJSON),
            authenticatorData: bufferToB64url(assertion.authenticatorData),
            signature: bufferToB64url(assertion.signature),
            userHandle: assertion.userHandle
              ? bufferToB64url(assertion.userHandle)
              : null,
          },
          clientExtensionResults: cred.getClientExtensionResults(),
        },
      };

      await api.post('/auth/webauthn/authenticate/finish', body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });
}

export function useWebAuthnDeleteCredential() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (credentialId: number) => {
      await api.delete(`/auth/webauthn/credentials/${credentialId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: WEBAUTHN_CREDENTIALS_KEY });
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
    },
  });
}
