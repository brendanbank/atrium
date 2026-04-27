// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { ME_QUERY_KEY } from './useAuth';

export interface TOTPState {
  enrolled: boolean;
  confirmed: boolean;
  email_otp_enrolled: boolean;
  email_otp_confirmed: boolean;
  webauthn_credential_count: number;
  session_passed: boolean;
}

export interface TOTPSetupResponse {
  secret: string;
  provisioning_uri: string;
}

export const TOTP_STATE_KEY = ['auth', 'totp', 'state'] as const;

export function useTOTPState() {
  return useQuery({
    queryKey: TOTP_STATE_KEY,
    queryFn: async () => (await api.get<TOTPState>('/auth/totp/state')).data,
    // Always refetch when the component mounts — the state flips
    // inside a single login session (partial → full after verify).
    staleTime: 0,
    refetchOnMount: 'always',
    retry: false,
  });
}

export function useTOTPSetup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post<TOTPSetupResponse>('/auth/totp/setup')).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
    },
  });
}

export function useTOTPConfirm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (code: string) => {
      await api.post('/auth/totp/confirm', { code });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });
}

export function useTOTPVerify() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (code: string) => {
      await api.post('/auth/totp/verify', { code });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });
}

export function useTOTPAdminReset() {
  return useMutation({
    mutationFn: async (userId: number) => {
      await api.post(`/admin/users/${userId}/totp/reset`);
    },
  });
}

export function useTOTPDisable() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.post('/auth/totp/disable');
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
    },
  });
}

// ---- Email OTP — parallel method to authenticator-app TOTP. ----

export function useEmailOTPSetup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.post('/auth/email-otp/setup');
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
    },
  });
}

export function useEmailOTPConfirm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (code: string) => {
      await api.post('/auth/email-otp/confirm', { code });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });
}

export function useEmailOTPRequest() {
  return useMutation({
    mutationFn: async () => {
      await api.post('/auth/email-otp/request');
    },
  });
}

export function useEmailOTPVerify() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (code: string) => {
      await api.post('/auth/email-otp/verify', { code });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
      qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });
}

export function useEmailOTPDisable() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.post('/auth/email-otp/disable');
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOTP_STATE_KEY });
    },
  });
}
