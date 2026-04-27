// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

export const ROLES_KEY = ['admin', 'roles'] as const;
export const PERMISSIONS_KEY = ['admin', 'permissions'] as const;

export interface Permission {
  code: string;
  description: string | null;
}

export interface Role {
  id: number;
  code: string;
  name: string;
  is_system: boolean;
  permissions: string[];
}

export interface RoleCreatePayload {
  code: string;
  name: string;
  permissions: string[];
}

export interface RoleUpdatePayload {
  name?: string;
  permissions?: string[];
}

export function usePermissions() {
  return useQuery({
    queryKey: PERMISSIONS_KEY,
    queryFn: async () => (await api.get<Permission[]>('/admin/permissions')).data,
  });
}

export function useRoles() {
  return useQuery({
    queryKey: ROLES_KEY,
    queryFn: async () => (await api.get<Role[]>('/admin/roles')).data,
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: RoleCreatePayload) =>
      (await api.post<Role>('/admin/roles', payload)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ROLES_KEY }),
  });
}

export function useUpdateRole(roleId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: RoleUpdatePayload) =>
      (await api.patch<Role>(`/admin/roles/${roleId}`, payload)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ROLES_KEY }),
  });
}

export function useDeleteRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (roleId: number) => {
      await api.delete(`/admin/roles/${roleId}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ROLES_KEY }),
  });
}
