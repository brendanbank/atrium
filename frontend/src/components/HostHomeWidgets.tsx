// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Fragment, type ReactElement } from 'react';
import { Container, Stack } from '@mantine/core';

import { getHomeWidgets, type HomeWidgetWidth } from '@/host/registry';

/** Wrap a widget element in the Container that matches its declared
 *  width. ``full`` renders without a Container so the widget owns the
 *  panel (handy for FullCalendar, large tables, anything that needs
 *  horizontal real estate). ``narrow`` (the default) keeps the 680px
 *  column atrium uses for its own welcome content so widgets that
 *  predate the ``width`` prop look exactly as they did. */
function widthContainer(
  child: ReactElement,
  width: HomeWidgetWidth | undefined,
  key: string,
): ReactElement {
  switch (width ?? 'narrow') {
    case 'full':
      return <Fragment key={key}>{child}</Fragment>;
    case 'wide':
      return (
        <Container key={key} size="lg">
          {child}
        </Container>
      );
    case 'narrow':
    default:
      return (
        <Container key={key} size={680}>
          {child}
        </Container>
      );
  }
}

/** Iterates the home-widget registry and renders each widget at its
 *  declared width above the atrium-shipped HomePage content. Empty
 *  when no host bundle is loaded. */
export function HostHomeWidgets() {
  const widgets = getHomeWidgets();
  if (widgets.length === 0) return null;
  return (
    <Stack gap="md">
      {widgets.map((w) => widthContainer(w.render(), w.width, w.key))}
    </Stack>
  );
}
