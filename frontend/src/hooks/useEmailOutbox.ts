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

/** Poll cadence for the outbox admin view. The cron worker ticks every
 *  60 s and a host's inline ``drain_outbox_row(...)`` call lands without
 *  notifying the SPA, so the queue otherwise stays stale until the
 *  operator hard-refreshes (#83). 8 s is short enough that a "did the
 *  email go out?" check during a phone call gets a fresh answer, and
 *  long enough that an idle admin tab isn't hammering the API.
 *
 *  ``refetchIntervalInBackground: false`` so a tab left open in another
 *  window doesn't poll. The next refetch fires the moment the tab
 *  regains focus. */
const OUTBOX_REFETCH_INTERVAL_MS = 8_000;

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
    refetchInterval: OUTBOX_REFETCH_INTERVAL_MS,
    refetchIntervalInBackground: false,
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
