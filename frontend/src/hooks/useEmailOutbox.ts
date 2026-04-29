// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

export type EmailOutboxStatus = 'pending' | 'sending' | 'sent' | 'dead';

export interface EmailOutboxRow {
  id: number;
  template: string;
  to_addr: string;
  locale: string;
  status: EmailOutboxStatus;
  attempts: number;
  last_error: string | null;
  next_attempt_at: string;
  created_at: string;
  updated_at: string;
  entity_type: string | null;
  entity_id: number | null;
}

export interface EmailOutboxPage {
  items: EmailOutboxRow[];
  total: number;
}

export interface DrainResult {
  id: number;
  status: EmailOutboxStatus;
  attempts: number;
  last_error: string | null;
  next_attempt_at: string;
}

export const EMAIL_OUTBOX_KEY = ['admin', 'email-outbox'] as const;

export function useEmailOutbox(params: {
  status?: EmailOutboxStatus | null;
  limit: number;
  offset: number;
}) {
  return useQuery({
    queryKey: [...EMAIL_OUTBOX_KEY, params.status ?? 'all', params.limit, params.offset],
    queryFn: async () => {
      const search = new URLSearchParams();
      if (params.status) search.set('status', params.status);
      search.set('limit', String(params.limit));
      search.set('offset', String(params.offset));
      const res = await api.get<EmailOutboxPage>(
        `/admin/email-outbox?${search.toString()}`,
      );
      return res.data;
    },
  });
}

/** Synchronously drain a single pending row. Resolves with the row's
 *  post-attempt status (``sent`` / ``pending`` / ``dead``) so the
 *  caller can render a ``notifications.show(...)`` describing what
 *  actually happened. Throws on 4xx — the UI bubbles the server's
 *  ``detail`` into the toast. */
export function useDrainOutboxRow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const res = await api.post<DrainResult>(
        `/admin/email-outbox/${id}/drain`,
      );
      return res.data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: EMAIL_OUTBOX_KEY });
    },
  });
}
