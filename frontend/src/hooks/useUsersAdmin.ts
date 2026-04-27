// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { CurrentUser } from '@/lib/auth';

export interface AdminUser extends CurrentUser {
  role_ids: number[];
}

const USERS_KEY = ['admin', 'users'] as const;
const INVITES_KEY = ['admin', 'invites'] as const;

export interface Invite {
  id: number;
  email: string;
  full_name: string;
  // RBAC role codes granted on accept (e.g. ["admin", "user"]).
  role_codes: string[];
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
}

export function useAdminUsers() {
  return useQuery({
    queryKey: USERS_KEY,
    queryFn: async () => (await api.get<AdminUser[]>('/admin/users')).data,
  });
}

export interface UserAdminPatch {
  is_active?: boolean;
  full_name?: string;
  email?: string;
  role_ids?: number[];
}

export function useUpdateAdminUser(userId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: UserAdminPatch) => {
      const { data } = await api.patch<AdminUser>(
        `/admin/users/${userId}`,
        payload,
      );
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useAdminResetPassword() {
  return useMutation({
    mutationFn: async (userId: number) => {
      await api.post(`/admin/users/${userId}/password-reset`);
    },
  });
}

export function useDeleteUserPermanent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: number) => {
      await api.delete(`/admin/users/${userId}/permanent`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useInvites() {
  return useQuery({
    queryKey: INVITES_KEY,
    queryFn: async () => (await api.get<Invite[]>('/invites')).data,
  });
}

export interface InvitePayload {
  email: string;
  full_name: string;
  // RBAC role codes to grant on accept. At least one required.
  role_codes: string[];
  expires_in_hours?: number;
}

export function useCreateInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: InvitePayload) =>
      (await api.post<Invite>('/invites', payload)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: INVITES_KEY }),
  });
}

export function useRevokeInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/invites/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: INVITES_KEY }),
  });
}
