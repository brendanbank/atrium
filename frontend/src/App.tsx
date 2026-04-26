import { Routes, Route, Navigate } from 'react-router-dom';

import { AppLayout } from './components/AppLayout';
import { RequireAuth } from './components/RequireAuth';
import { AcceptInvitePage } from './routes/AcceptInvitePage';
import { AdminPage } from './routes/AdminPage';
import { ForgotPasswordPage } from './routes/ForgotPasswordPage';
import { HomePage } from './routes/HomePage';
import { LoginPage } from './routes/LoginPage';
import { NotificationsPage } from './routes/NotificationsPage';
import { ProfilePage } from './routes/ProfilePage';
import { ResetPasswordPage } from './routes/ResetPasswordPage';
import { TwoFactorPage } from './routes/TwoFactorPage';

export default function App() {
  return (
    <Routes>
      {/* Public auth routes (no layout) */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/accept-invite" element={<AcceptInvitePage />} />
      {/* 2FA gate — needs a partial session, so it lives outside
          RequireAuth (which only understands full sessions). */}
      <Route path="/2fa" element={<TwoFactorPage />} />

      {/* Authenticated routes (inside app shell) */}
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
