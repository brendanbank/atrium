import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

export interface EmailTemplate {
  key: string;
  subject: string;
  body_html: string;
  description: string | null;
  updated_at: string;
}

const KEY = ['admin', 'email-templates'] as const;

export function useEmailTemplates() {
  return useQuery({
    queryKey: KEY,
    queryFn: async () =>
      (await api.get<EmailTemplate[]>('/admin/email-templates')).data,
  });
}

export function useUpdateEmailTemplate(key: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      subject?: string;
      body_html?: string;
      description?: string | null;
    }) =>
      (await api.patch<EmailTemplate>(`/admin/email-templates/${key}`, payload))
        .data,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
