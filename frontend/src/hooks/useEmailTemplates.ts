// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

export interface EmailTemplate {
  key: string;
  locale: string;
  subject: string;
  body_html: string;
  description: string | null;
  updated_at: string;
}

const KEY = ['admin', 'email-templates'] as const;

const variantKey = (key: string, locale: string) =>
  ['admin', 'email-templates', key, locale] as const;

export function useEmailTemplates() {
  return useQuery({
    queryKey: KEY,
    queryFn: async () =>
      (await api.get<EmailTemplate[]>('/admin/email-templates')).data,
  });
}

/** Fetch a specific (key, locale) row.
 *
 * The admin UI calls this whenever the locale picker changes inside a
 * modal so CKEditor's body always reflects the row the next save will
 * PATCH. ``enabled`` lets the caller short-circuit until both axes
 * are known (the modal mounts with no template selected). */
export function useEmailTemplate(
  key: string | null,
  locale: string | null,
) {
  return useQuery({
    queryKey: variantKey(key ?? '', locale ?? ''),
    enabled: !!key && !!locale,
    queryFn: async () =>
      (
        await api.get<EmailTemplate>(
          `/admin/email-templates/${key}/${locale}`,
        )
      ).data,
    // 404 when the variant doesn't exist yet — we treat that as
    // "author a fresh row" rather than an error in the UI.
    retry: false,
  });
}

export function useUpdateEmailTemplate(key: string, locale: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      subject?: string;
      body_html?: string;
      description?: string | null;
    }) =>
      (
        await api.patch<EmailTemplate>(
          `/admin/email-templates/${key}/${locale}`,
          payload,
        )
      ).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
      qc.invalidateQueries({ queryKey: variantKey(key, locale) });
    },
  });
}
