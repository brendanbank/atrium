// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { dispatchAtriumEvent, parseAtriumEvent } from '@/host/events';
import { NOTIFS_LIST_KEY, NOTIFS_UNREAD_KEY } from './useNotifications';

/**
 * Subscribe to the notifications SSE stream.
 *
 * Atrium owns one ``EventSource('/notifications/stream')`` per tab —
 * this hook is the owner. Two responsibilities, one connection:
 *
 *  - Refresh the bell. The bell unconditionally invalidates its list
 *    + unread-count queries on every push, regardless of kind. The
 *    presence of an event is the signal; the row content is fetched
 *    out of band.
 *  - Fan the typed event out to host subscribers via the event bus
 *    in ``host/events.ts``. Hosts call ``subscribeEvent(kind, fn)``
 *    on the host-extension registry (or directly from in-tree code)
 *    and route the kind to selective React Query invalidations.
 *
 * EventSource handles auto-reconnect on network blips — no manual
 * retry needed. The stream reuses the JWT httpOnly cookie for auth
 * because ``EventSource`` sends credentials same-origin
 * automatically.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';

export function useNotificationStream(enabled: boolean) {
  const qc = useQueryClient();

  useEffect(() => {
    if (!enabled || typeof EventSource === 'undefined') return;

    const url = `${BASE_URL}/notifications/stream`;
    const es = new EventSource(url, { withCredentials: true });

    const onPush = (e: MessageEvent) => {
      qc.invalidateQueries({ queryKey: NOTIFS_LIST_KEY });
      qc.invalidateQueries({ queryKey: NOTIFS_UNREAD_KEY });
      const evt = parseAtriumEvent(e.data);
      if (evt) dispatchAtriumEvent(evt);
    };

    es.addEventListener('notification', onPush as EventListener);

    // `error` fires on disconnect; EventSource will retry automatically
    // (default 3s; backend sends `retry: 2000` to override). If the
    // user has logged out, the server will 401 on reconnect — we close
    // the stream explicitly when `enabled` flips false (the effect
    // cleanup below does that).
    es.addEventListener('error', () => {
      // Intentionally no-op: let the browser's built-in retry handle it.
    });

    return () => {
      es.removeEventListener('notification', onPush as EventListener);
      es.close();
    };
  }, [enabled, qc]);
}
