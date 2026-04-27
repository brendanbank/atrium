// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchMe, logout as apiLogout, type CurrentUser } from '@/lib/auth';

export const ME_QUERY_KEY = ['me'] as const;

export function useMe() {
  return useQuery<CurrentUser | null>({
    queryKey: ME_QUERY_KEY,
    queryFn: fetchMe,
    staleTime: 60_000,
    retry: false,
  });
}

export function usePerm(code: string): boolean {
  const { data: me } = useMe();
  return (me?.permissions ?? []).includes(code);
}

export function useLogout() {
  const qc = useQueryClient();
  return async () => {
    await apiLogout();
    // Wipe the whole TanStack cache. `invalidateQueries` only marks
    // entries stale — on the next login any consumer that mounts
    // before its refetch lands (notably `useTOTPState` on /2fa) would
    // read the previous session's `session_passed: true` and bounce
    // the user away from the challenge screen.
    qc.clear();
  };
}
