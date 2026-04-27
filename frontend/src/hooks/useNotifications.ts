// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

/** Kind code on a notification row. Atrium ships no built-in kinds —
 *  host apps emit whatever string codes their domain needs. */
export type NotificationKind = string;

export interface AppNotification {
  id: number;
  kind: NotificationKind;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

export const NOTIFS_LIST_KEY = ['notifications'] as const;
export const NOTIFS_UNREAD_KEY = ['notifications', 'unread'] as const;
// Back-compat aliases for in-file usage below.
const NOTIFS_KEY = NOTIFS_LIST_KEY;
const UNREAD_KEY = NOTIFS_UNREAD_KEY;

export function useNotifications() {
  return useQuery({
    queryKey: NOTIFS_KEY,
    queryFn: async () => {
      const { data } = await api.get<AppNotification[]>('/notifications', {
        params: { limit: 50 },
      });
      return data;
    },
    staleTime: 15_000,
  });
}

export function useUnreadCount() {
  return useQuery({
    queryKey: UNREAD_KEY,
    queryFn: async () => {
      const { data } = await api.get<{ count: number }>(
        '/notifications/unread-count',
      );
      return data.count;
    },
    // SSE handles freshness; keep refetchOnWindowFocus as a safety net
    // for tabs that missed a push while the device was asleep.
    refetchOnWindowFocus: true,
    staleTime: 10_000,
  });
}


export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.post(`/notifications/${id}/read`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: NOTIFS_KEY });
      qc.invalidateQueries({ queryKey: UNREAD_KEY });
    },
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.post('/notifications/mark-all-read');
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: NOTIFS_KEY });
      qc.invalidateQueries({ queryKey: UNREAD_KEY });
    },
  });
}

export function useDeleteNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/notifications/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: NOTIFS_KEY });
      qc.invalidateQueries({ queryKey: UNREAD_KEY });
    },
  });
}
