// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Fragment } from 'react';
import { Stack } from '@mantine/core';

import { getHomeWidgets } from '@/host/registry';

/** Iterates the home-widget registry and renders each widget in a
 *  vertical Mantine Stack above the atrium-shipped HomePage content.
 *  Empty when no host bundle is loaded. */
export function HostHomeWidgets() {
  const widgets = getHomeWidgets();
  if (widgets.length === 0) return null;
  return (
    <Stack gap="md">
      {widgets.map((w) => (
        <Fragment key={w.key}>{w.render()}</Fragment>
      ))}
    </Stack>
  );
}
