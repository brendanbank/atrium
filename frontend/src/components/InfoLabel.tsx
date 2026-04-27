// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { Group, Text, Tooltip } from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';
import type { ReactNode } from 'react';

interface Props {
  label: ReactNode;
  help: ReactNode;
  required?: boolean;
}

/**
 * Form label with an info icon that reveals help text on hover / focus.
 * Use in place of the `description` prop when you want the help text
 * hidden by default.
 */
export function InfoLabel({ label, help, required }: Props) {
  return (
    <Group gap={4} wrap="nowrap" style={{ display: 'inline-flex' }}>
      <Text component="span" size="sm" fw={500}>
        {label}
        {required && (
          <Text component="span" c="red.6" ml={2}>
            *
          </Text>
        )}
      </Text>
      <Tooltip label={help} multiline maw={260} withArrow position="top">
        <IconInfoCircle
          size={14}
          tabIndex={0}
          style={{ cursor: 'help', opacity: 0.55 }}
          aria-label="More info"
        />
      </Tooltip>
    </Group>
  );
}
