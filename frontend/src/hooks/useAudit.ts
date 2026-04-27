// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

export interface AuditEntry {
  id: number;
  actor_user_id: number | null;
  actor_email: string | null;
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

export interface AuditParams {
  entity?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export function useAuditLog(params: AuditParams) {
  return useQuery({
    queryKey: ['audit', params],
    queryFn: async () =>
      (await api.get<AuditPage>('/admin/audit', { params })).data,
    staleTime: 10_000,
  });
}
