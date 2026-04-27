// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { ReactNode } from 'react';
import { Center, Loader } from '@mantine/core';
import { Navigate, useLocation } from 'react-router-dom';

import { useMe } from '@/hooks/useAuth';

interface Props {
  children: ReactNode;
  /** Optional RBAC role code the user must hold (e.g. ``"admin"``). */
  role?: string;
}

export function RequireAuth({ children, role }: Props) {
  const { data, isLoading, isFetching } = useMe();
  const location = useLocation();

  // isLoading = first load with no cache; isFetching covers revalidation
  // so a stale `null` from the pre-login probe can't cause a bounce while
  // the refetch is in flight.
  if (isLoading || (data == null && isFetching)) {
    return (
      <Center h="60vh">
        <Loader />
      </Center>
    );
  }

  if (!data) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }

  if (role && !data.roles.includes(role)) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
