// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { ME_QUERY_KEY } from './useAuth';

export interface AuthSessionRead {
  id: number;
  session_id: string;
  issued_at: string;
  expires_at: string;
  user_agent: string | null;
  ip: string | null;
  is_current: boolean;
}

export const SESSIONS_KEY = ['auth', 'sessions'] as const;

export function useSessions() {
  return useQuery({
    queryKey: SESSIONS_KEY,
    queryFn: async () =>
      (await api.get<AuthSessionRead[]>('/auth/sessions')).data,
    // Don't poll — the list is short-lived info and we refetch after
    // logout-all anyway.
    staleTime: 30_000,
  });
}

export function useLogoutAll() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.post('/auth/logout-all');
    },
    onSuccess: () => {
      // Everything the caller knew about is gone — wipe the cache so
      // the next page paint reflects the logged-out state, and the
      // me-probe (/users/me) bounces them to /login.
      qc.setQueryData(ME_QUERY_KEY, null);
      qc.clear();
    },
  });
}
