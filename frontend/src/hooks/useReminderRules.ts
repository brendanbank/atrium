// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

// Atrium ships no built-in anchors or kinds — host apps register
// the values that make sense for them and the admin UI accepts both
// as free-form strings.
export type ReminderKind = string;
export type ReminderAnchor = string;

export interface ReminderRule {
  id: number;
  name: string;
  template_key: string;
  kind: ReminderKind;
  anchor: ReminderAnchor;
  days_offset: number;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ReminderRulePayload {
  name: string;
  template_key: string;
  kind: ReminderKind;
  anchor: ReminderAnchor;
  days_offset: number;
  active?: boolean;
}

const KEY = ['admin', 'reminder-rules'] as const;

export function useReminderRules() {
  return useQuery({
    queryKey: KEY,
    queryFn: async () =>
      (await api.get<ReminderRule[]>('/admin/reminder-rules')).data,
  });
}

export function useCreateReminderRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ReminderRulePayload) =>
      (await api.post<ReminderRule>('/admin/reminder-rules', payload)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateReminderRule(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Partial<ReminderRulePayload>) =>
      (await api.patch<ReminderRule>(`/admin/reminder-rules/${id}`, payload))
        .data,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteReminderRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/admin/reminder-rules/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
