// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Routes, Route, Navigate } from 'react-router-dom';

import { AppLayout } from './components/AppLayout';
import { MaintenancePage } from './components/MaintenancePage';
import { RequireAuth } from './components/RequireAuth';
import { useAppConfig } from './hooks/useAppConfig';
import { useMe } from './hooks/useAuth';
import { ColorSchemeBridge } from './host/color-scheme';
import { IdentityBridge } from './host/identity';
import { NavigationBridge } from './host/navigation';
import { getRoutes } from './host/registry';
import { AcceptInvitePage } from './routes/AcceptInvitePage';
import { SectionPage } from './routes/AdminPage';
import { ForgotPasswordPage } from './routes/ForgotPasswordPage';
import { HomePage } from './routes/HomePage';
import { LoginPage } from './routes/LoginPage';
import { NotificationsPage } from './routes/NotificationsPage';
import { ProfilePage } from './routes/ProfilePage';
import { RegisterPage } from './routes/RegisterPage';
import { ResetPasswordPage } from './routes/ResetPasswordPage';
import { TwoFactorPage } from './routes/TwoFactorPage';
import { VerifyEmailPage } from './routes/VerifyEmailPage';

export default function App() {
  const { data: appConfig } = useAppConfig();
  const { data: me } = useMe();
  // Maintenance gate is enforced server-side by MaintenanceMiddleware;
  // this is the UI half so non-super_admins see a friendly page rather
  // than a forest of 503 toasts. Login + reset-password are still
  // reachable so a super_admin can sign in to flip the flag back —
  // those routes appear *before* this guard.
  const maintenanceOn = appConfig?.system?.maintenance_mode === true;
  const isSuperAdmin = me?.roles.includes('super_admin') ?? false;
  if (maintenanceOn && !isSuperAdmin) {
    return (
      <>
        <NavigationBridge />
        <IdentityBridge />
        <ColorSchemeBridge />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/2fa" element={<TwoFactorPage />} />
          <Route path="*" element={<MaintenancePage />} />
        </Routes>
      </>
    );
  }
  // Host bundles register additional routes via getRoutes(); split
  // by ``layout``+``requireAuth`` so shell-routes nest inside the
  // existing AppLayout/RequireAuth wrapper (whose <Outlet/> renders
  // the matched child) and bare routes mount outside it.
  const hostRoutes = getRoutes();
  const shellAuthRoutes = hostRoutes.filter(
    (r) => (r.layout ?? 'shell') === 'shell' && (r.requireAuth ?? true),
  );
  const bareAuthRoutes = hostRoutes.filter(
    (r) => (r.layout ?? 'shell') === 'bare' && (r.requireAuth ?? true),
  );
  const publicHostRoutes = hostRoutes.filter(
    (r) => (r.requireAuth ?? true) === false,
  );
  return (
    <>
      <NavigationBridge />
      <IdentityBridge />
      <ColorSchemeBridge />
      <Routes>
        {/* Public auth routes (no layout) */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/accept-invite" element={<AcceptInvitePage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        {/* 2FA gate — needs a partial session, so it lives outside
            RequireAuth (which only understands full sessions). */}
        <Route path="/2fa" element={<TwoFactorPage />} />

        {publicHostRoutes.map((r) => (
          <Route
            key={r.key}
            path={r.path}
            element={r.render ? r.render() : r.element}
          />
        ))}

        {bareAuthRoutes.map((r) => (
          <Route
            key={r.key}
            path={r.path}
            element={
              <RequireAuth>{r.render ? r.render() : r.element}</RequireAuth>
            }
          />
        ))}

        {/* Authenticated routes (inside app shell) */}
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route index element={<HomePage />} />
          <Route path="/admin" element={<SectionPage bucket="admin" />} />
          <Route
            path="/admin/:section"
            element={<SectionPage bucket="admin" />}
          />
          <Route path="/settings" element={<SectionPage bucket="settings" />} />
          <Route
            path="/settings/:section"
            element={<SectionPage bucket="settings" />}
          />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          {shellAuthRoutes.map((r) => (
            <Route
              key={r.key}
              path={r.path}
              element={r.render ? r.render() : r.element}
            />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  );
}
