// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { QueryClient } from '@tanstack/react-query';

/** Single QueryClient shared across the home widget, the dedicated
 *  page, and the admin tab. Each one wraps its element in a
 *  QueryClientProvider that points at this client so they share the
 *  cache for ``['hello', 'state']``. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2_000,
      refetchInterval: 5_000,
      retry: 1,
    },
  },
});
