// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

export interface SelfDeleteVariables {
  password: string;
}

export function useSelfDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ password }: SelfDeleteVariables) => {
      await api.post('/users/me/delete', { password });
    },
    onSuccess: () => {
      qc.clear();
    },
  });
}
