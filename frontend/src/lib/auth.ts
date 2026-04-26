import { api } from './api';

export type Language = 'en' | 'nl';

export interface CurrentUser {
  id: number;
  email: string;
  full_name: string;
  phone: string | null;
  preferred_language: Language;
  is_active: boolean;
  is_verified: boolean;
  is_superuser: boolean;
  // Populated from /users/me/context — RBAC role codes, permission
  // codes, plus the original user if this session is an impersonation.
  // All default to safe-empty values when the context call hasn't
  // landed yet.
  roles: string[];
  permissions: string[];
  impersonating_from: { id: number; email: string; full_name: string } | null;
}

interface MeContextResponse {
  id: number;
  email: string;
  full_name: string;
  roles: string[];
  is_active: boolean;
  permissions: string[];
  impersonating_from: { id: number; email: string; full_name: string } | null;
}

export async function fetchMe(): Promise<CurrentUser | null> {
  try {
    // /users/me/context returns the runtime RBAC context. For the
    // self-service fields (phone, preferred_language, is_verified,
    // is_superuser) we still need /users/me — fetch both in parallel.
    const [baseResp, ctxResp] = await Promise.all([
      api.get<CurrentUser>('/users/me'),
      api.get<MeContextResponse>('/users/me/context'),
    ]);
    return {
      ...baseResp.data,
      roles: ctxResp.data.roles,
      permissions: ctxResp.data.permissions,
      impersonating_from: ctxResp.data.impersonating_from,
    };
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status === 401) return null;
    throw err;
  }
}

export async function impersonate(
  userId: number,
): Promise<{ id: number; email: string; full_name: string }> {
  const { data } = await api.post<{ id: number; email: string; full_name: string }>(
    `/admin/users/${userId}/impersonate`,
  );
  return data;
}

export async function stopImpersonating(): Promise<{
  id: number;
  email: string;
  full_name: string;
}> {
  const { data } = await api.post<{ id: number; email: string; full_name: string }>(
    '/admin/impersonate/stop',
  );
  return data;
}

export async function login(email: string, password: string): Promise<void> {
  // fastapi-users' JWT login endpoint expects form-encoded "username" + "password"
  const body = new URLSearchParams({ username: email, password });
  await api.post('/auth/jwt/login', body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
}

export async function logout(): Promise<void> {
  await api.post('/auth/jwt/logout');
}

export async function updateMe(payload: Partial<Pick<CurrentUser, 'full_name' | 'phone' | 'preferred_language' | 'email'>> & { password?: string }): Promise<CurrentUser> {
  const { data } = await api.patch<CurrentUser>('/users/me', payload);
  return data;
}

export async function acceptInvite(token: string, password: string): Promise<void> {
  await api.post('/invites/accept', { token, password });
}

export async function forgotPassword(email: string): Promise<void> {
  await api.post('/auth/forgot-password', { email });
}

export async function resetPassword(token: string, password: string): Promise<void> {
  await api.post('/auth/reset-password', { token, password });
}
