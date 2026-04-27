// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { NOTIFS_LIST_KEY, NOTIFS_UNREAD_KEY } from './useNotifications';

/**
 * Subscribe to the notifications SSE stream and invalidate the bell's
 * React Query caches whenever a push arrives. EventSource handles
 * auto-reconnect on network blips — no manual retry needed.
 *
 * The stream reuses the JWT httpOnly cookie for auth because
 * `EventSource` sends credentials same-origin automatically.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

export function useNotificationStream(enabled: boolean) {
  const qc = useQueryClient();

  useEffect(() => {
    if (!enabled || typeof EventSource === 'undefined') return;

    const url = `${BASE_URL}/notifications/stream`;
    const es = new EventSource(url, { withCredentials: true });

    const onPush = () => {
      qc.invalidateQueries({ queryKey: NOTIFS_LIST_KEY });
      qc.invalidateQueries({ queryKey: NOTIFS_UNREAD_KEY });
    };

    es.addEventListener('notification', onPush);

    // `error` fires on disconnect; EventSource will retry automatically
    // (default 3s). If the user has logged out, the server will 401 on
    // reconnect — we close the stream explicitly when `enabled` flips
    // false (the effect cleanup below does that).
    es.addEventListener('error', () => {
      // Intentionally no-op: let the browser's built-in retry handle it.
    });

    return () => {
      es.removeEventListener('notification', onPush);
      es.close();
    };
  }, [enabled, qc]);
}
