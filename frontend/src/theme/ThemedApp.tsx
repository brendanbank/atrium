// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useMemo } from 'react';
import { MantineProvider } from '@mantine/core';

import { useAppConfig } from '@/hooks/useAppConfig';

import { buildTheme, colorSchemeForPreset } from '.';

// Wraps MantineProvider with a theme rebuilt whenever app-config
// changes. Lives inside QueryClientProvider so the hook resolves;
// kept in its own file so vite HMR can refresh main.tsx without
// resetting the provider tree.
export function ThemedApp({ children }: { children: React.ReactNode }) {
  const { data } = useAppConfig();
  const brand = data?.brand;
  const theme = useMemo(() => buildTheme(brand), [brand]);
  const scheme = colorSchemeForPreset(brand?.preset ?? 'default');
  // Mirror brand.name into document.title so a tenant that renamed
  // the brand isn't stuck with the literal "Atrium" baked into
  // index.html (issue #99). Runs every time the bundle refetches so
  // an admin rename propagates without a hard reload.
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const name = brand?.name?.trim();
    if (name) document.title = name;
  }, [brand?.name]);
  return (
    <MantineProvider theme={theme} defaultColorScheme={scheme}>
      {children}
    </MantineProvider>
  );
}
