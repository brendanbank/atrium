// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Alert } from '@mantine/core';
import { IconInfoCircle, IconAlertTriangle, IconAlertOctagon } from '@tabler/icons-react';

import { useAppConfig } from '@/hooks/useAppConfig';

const COLOR_FOR_LEVEL: Record<string, string> = {
  info: 'blue',
  warning: 'yellow',
  critical: 'red',
};

const ICON_FOR_LEVEL: Record<string, React.ReactNode> = {
  info: <IconInfoCircle size={18} />,
  warning: <IconAlertTriangle size={18} />,
  critical: <IconAlertOctagon size={18} />,
};

// Renders above the app shell when system.announcement is set. Plain
// text only — see SystemConfig.announcement comment in the backend
// for the XSS rationale.
export function AnnouncementBanner() {
  const { data } = useAppConfig();
  const announcement = data?.system?.announcement?.trim();
  if (!announcement) return null;
  const level = data?.system?.announcement_level ?? 'info';
  return (
    <Alert
      color={COLOR_FOR_LEVEL[level] ?? 'blue'}
      icon={ICON_FOR_LEVEL[level]}
      radius={0}
      mb={0}
      style={{ borderRadius: 0 }}
      // ``data-level`` is the e2e-test seam — Mantine v9 doesn't
      // expose the colour name as an attribute, only as a computed
      // style that resolves to a hex value.
      data-level={level}
    >
      {announcement}
    </Alert>
  );
}
