// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { lookupNotificationRenderer } from '@/host/registry';
import type { AppNotification } from '@/hooks/useNotifications';

/** Compact summary string for the bell list / inbox row.
 *
 *  Atrium ships a kind-agnostic fallback: each row shows the raw
 *  ``kind`` code. Host apps swap in friendlier per-kind text by
 *  registering ``__ATRIUM_REGISTRY__.registerNotificationKind({ kind,
 *  title, ... })`` — when a renderer is registered with a ``title``
 *  helper, atrium calls it here. The detail-modal body uses
 *  ``render`` (a full React element); this row helper deliberately
 *  stays string-only so the inbox iterates cheaply. */
export function renderNotificationBody(n: AppNotification): string {
  const title = lookupNotificationRenderer(n.kind)?.title;
  if (title) {
    try {
      return title(n);
    } catch (err) {
      // A bad host renderer must not poison the whole bell list.
      console.warn(
        `[atrium] notification title() for kind "${n.kind}" threw; ` +
          `falling back to kind code`,
        err,
      );
    }
  }
  return n.kind;
}
