import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

export type ThemePreset = 'default' | 'dark-glass' | 'classic';

export interface BrandConfig {
  name: string;
  logo_url: string | null;
  support_email: string | null;
  preset: ThemePreset;
  overrides: Record<string, string>;
}

export type AnnouncementLevel = 'info' | 'warning' | 'critical';

export interface SystemConfig {
  maintenance_mode: boolean;
  maintenance_message: string;
  announcement: string | null;
  announcement_level: AnnouncementLevel;
}

export interface I18nConfig {
  enabled_locales: string[];
  overrides: Record<string, Record<string, string>>;
}

export type CaptchaProvider = 'none' | 'turnstile' | 'hcaptcha';

export interface PublicAuthConfig {
  // Carve-out from AuthConfig — the full auth namespace stays
  // admin-only (password policy etc.), but the LoginPage needs to
  // know whether to render the "Sign up" link.
  allow_signup: boolean;
  // CAPTCHA: provider + site_key are public (the widget renders them
  // into the page source). The secret never leaves the backend.
  captcha_provider: CaptchaProvider;
  captcha_site_key: string | null;
}

export interface PublicAppConfig {
  brand: BrandConfig;
  system?: SystemConfig;
  i18n?: I18nConfig;
  auth?: PublicAuthConfig;
}

export type AdminAppConfig = Record<string, Record<string, unknown>>;

const PUBLIC_KEY = ['app-config'] as const;
const ADMIN_KEY = ['admin', 'app-config'] as const;

export function useAppConfig() {
  return useQuery({
    queryKey: PUBLIC_KEY,
    queryFn: async () => (await api.get<PublicAppConfig>('/app-config')).data,
    // /app-config is hit on every cold load before /users/me — if we
    // refetch on every focus, the Mantine theme would flicker on tab
    // switches. The admin Branding form invalidates this key on save.
    staleTime: Infinity,
    retry: false,
  });
}

export function useAdminAppConfig() {
  return useQuery({
    queryKey: ADMIN_KEY,
    queryFn: async () =>
      (await api.get<AdminAppConfig>('/admin/app-config')).data,
  });
}

// Mutation accepts any serialisable object; the server runs the
// payload through the namespace's Pydantic model and returns 400 on
// shape mismatch, so we don't try to mirror that shape on the client.
export function useUpdateAppConfigNamespace<T = Record<string, unknown>>(
  namespace: string,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: T) =>
      (
        await api.put<Record<string, unknown>>(
          `/admin/app-config/${namespace}`,
          payload,
        )
      ).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ADMIN_KEY });
      qc.invalidateQueries({ queryKey: PUBLIC_KEY });
    },
  });
}
