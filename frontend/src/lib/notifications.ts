import type { AppNotification } from '@/hooks/useNotifications';

/** Atrium ships a kind-agnostic notification renderer. The backend
 *  emits `{kind, payload}` rows; host apps pick which kinds to show
 *  prettily, and everything else falls through to this generic
 *  rendering of the kind code plus a "View" affordance for the raw
 *  payload. Override by re-exporting your own version from this path. */
export function renderNotificationBody(n: AppNotification): string {
  return n.kind;
}
