// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

// Shared frontend types. Most domain types live alongside the hooks
// that fetch them (see hooks/useNotifications, useUsersAdmin, etc.);
// this module re-exports the cross-cutting ones for convenience.

export type { CurrentUser as User, Language } from './auth';
export type {
  AppNotification as Notification,
  NotificationKind,
} from '@/hooks/useNotifications';
export type { Permission, Role } from '@/hooks/useRolesAdmin';
export type { Invite, AdminUser } from '@/hooks/useUsersAdmin';
export type {
  ReminderRule,
  ReminderRulePayload,
  ReminderKind,
} from '@/hooks/useReminderRules';
export type { EmailTemplate } from '@/hooks/useEmailTemplates';
export type {
  BrandConfig,
  PublicAppConfig,
  SystemConfig,
  ThemePreset,
} from '@/hooks/useAppConfig';
export type { AuthSessionRead as AuthSession } from '@/hooks/useSessions';
export type { AuditEntry as AuditLog } from '@/hooks/useAudit';
