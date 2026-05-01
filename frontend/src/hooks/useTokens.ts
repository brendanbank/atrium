// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

/**
 * TanStack Query hooks for the Phase 2 PAT endpoints.
 *
 * The plaintext token (only present on POST and rotate responses)
 * is returned to the caller's mutation handler but never persisted in
 * the query cache — every list query strips it. The reveal modal
 * holds it in component-local React state and discards it on dismiss
 * (spec §3, "plaintext token must never round-trip through TanStack
 * Query state").
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';

import { api } from '@/lib/api';

export const TOKENS_KEY = ['auth', 'tokens'] as const;
export const ADMIN_TOKENS_KEY = ['admin', 'auth', 'tokens'] as const;
export const ADMIN_TOKEN_AUDIT_KEY = ['admin', 'auth', 'tokens', 'audit'] as const;
export const SERVICE_ACCOUNTS_KEY = ['admin', 'service_accounts'] as const;

export type TokenStatus = 'active' | 'expired' | 'revoked';

export interface TokenSummary {
  id: number;
  name: string;
  description: string | null;
  token_prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  last_used_ip: string | null;
  use_count: number;
  created_at: string;
  revoked_at: string | null;
  revoke_reason: string | null;
  status: TokenStatus;
}

export interface TokenCreated extends TokenSummary {
  /** Plaintext token. Present only on create + rotate responses. */
  token: string;
}

export interface AdminTokenSummary extends TokenSummary {
  user_id: number;
  user_email: string;
  user_full_name: string;
  revoked_by_user_id: number | null;
}

export interface TokenPage {
  items: AdminTokenSummary[];
  total: number;
}

export interface AuditEntry {
  id: number;
  actor_user_id: number | null;
  impersonator_user_id: number | null;
  token_id: number | null;
  entity: string;
  entity_id: number;
  action: string;
  diff: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
}

export interface ServiceAccountRead {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  description: string | null;
  created_at: string;
}

export interface ServiceAccountCreated {
  account: ServiceAccountRead;
  token: TokenCreated;
}

export interface CreateTokenPayload {
  name: string;
  description?: string | null;
  scopes: string[];
  /** ``null`` = no expiry. Capped server-side at ``pats.max_lifetime_days``. */
  expires_in_days: number | null;
}

export interface UpdateTokenPayload {
  name?: string;
  description?: string | null;
  scopes?: string[];
  expires_at?: string | null;
  clear_expiry?: boolean;
}

export interface CreateServiceAccountPayload {
  name: string;
  email: string;
  description?: string | null;
  role_codes: string[];
  initial_scopes: string[];
  expires_in_days: number | null;
}

export interface AdminTokensQuery {
  user_id?: number;
  status?: TokenStatus;
  unused_for_days?: number;
  expiring_within_days?: number;
  limit?: number;
  offset?: number;
}

export function useTokens(
  status?: TokenStatus,
): UseQueryResult<TokenSummary[]> {
  return useQuery({
    queryKey: [...TOKENS_KEY, status ?? 'all'] as const,
    queryFn: async () => {
      const resp = await api.get<TokenSummary[]>('/auth/tokens', {
        params: status ? { status } : undefined,
      });
      return resp.data;
    },
  });
}

export function useCreateToken() {
  const qc = useQueryClient();
  return useMutation<TokenCreated, Error, CreateTokenPayload>({
    mutationFn: async (payload) =>
      (await api.post<TokenCreated>('/auth/tokens', payload)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TOKENS_KEY });
    },
  });
}

export function useUpdateToken() {
  const qc = useQueryClient();
  return useMutation<
    TokenSummary,
    Error,
    { id: number; payload: UpdateTokenPayload }
  >({
    mutationFn: async ({ id, payload }) =>
      (await api.patch<TokenSummary>(`/auth/tokens/${id}`, payload)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TOKENS_KEY });
    },
  });
}

export function useRotateToken() {
  const qc = useQueryClient();
  return useMutation<TokenCreated, Error, number>({
    mutationFn: async (id) =>
      (await api.post<TokenCreated>(`/auth/tokens/${id}/rotate`)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TOKENS_KEY });
    },
  });
}

export function useRevokeToken() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: number; reason?: string }>({
    mutationFn: async ({ id, reason }) => {
      await api.delete(`/auth/tokens/${id}`, {
        data: reason ? { reason } : undefined,
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: TOKENS_KEY });
    },
  });
}

export function useAdminTokens(
  query: AdminTokensQuery = {},
): UseQueryResult<TokenPage> {
  return useQuery({
    queryKey: [...ADMIN_TOKENS_KEY, query] as const,
    queryFn: async () => {
      const params: Record<string, string | number> = {};
      if (query.user_id !== undefined) params.user_id = query.user_id;
      if (query.status !== undefined) params.status = query.status;
      if (query.unused_for_days !== undefined) {
        params.unused_for_days = query.unused_for_days;
      }
      if (query.expiring_within_days !== undefined) {
        params.expiring_within_days = query.expiring_within_days;
      }
      if (query.limit !== undefined) params.limit = query.limit;
      if (query.offset !== undefined) params.offset = query.offset;
      const resp = await api.get<TokenPage>('/admin/auth/tokens', {
        params,
      });
      return resp.data;
    },
  });
}

export function useAdminRevokeToken() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: number; reason: string }>({
    mutationFn: async ({ id, reason }) => {
      await api.delete(`/admin/auth/tokens/${id}`, {
        data: { reason },
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ADMIN_TOKENS_KEY });
      void qc.invalidateQueries({ queryKey: TOKENS_KEY });
    },
  });
}

export function useAdminRevokeAll() {
  const qc = useQueryClient();
  return useMutation<
    { user_id: number; revoked_count: number; reason: string },
    Error,
    { user_id: number; reason: string }
  >({
    mutationFn: async (payload) =>
      (
        await api.post<{ user_id: number; revoked_count: number; reason: string }>(
          '/admin/auth/tokens/revoke_all',
          payload,
        )
      ).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ADMIN_TOKENS_KEY });
      void qc.invalidateQueries({ queryKey: TOKENS_KEY });
    },
  });
}

export function useAdminTokenAudit(
  tokenId: number | null,
): UseQueryResult<AuditPage> {
  return useQuery({
    queryKey: [...ADMIN_TOKEN_AUDIT_KEY, tokenId] as const,
    queryFn: async () => {
      const resp = await api.get<AuditPage>(
        `/admin/auth/tokens/${tokenId}/audit`,
      );
      return resp.data;
    },
    enabled: tokenId !== null,
  });
}

export function useServiceAccounts(): UseQueryResult<ServiceAccountRead[]> {
  return useQuery({
    queryKey: SERVICE_ACCOUNTS_KEY,
    queryFn: async () =>
      (await api.get<ServiceAccountRead[]>('/admin/service_accounts')).data,
  });
}

export function useCreateServiceAccount() {
  const qc = useQueryClient();
  return useMutation<
    ServiceAccountCreated,
    Error,
    CreateServiceAccountPayload
  >({
    mutationFn: async (payload) =>
      (
        await api.post<ServiceAccountCreated>(
          '/admin/service_accounts',
          payload,
        )
      ).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: SERVICE_ACCOUNTS_KEY });
      void qc.invalidateQueries({ queryKey: ADMIN_TOKENS_KEY });
    },
  });
}
