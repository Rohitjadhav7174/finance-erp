import { Box, Paper, Text, UnstyledButton } from '@mantine/core';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { IconChevronRight } from '../layout/icons';

/** A clean settings-style list: icon chip, label, optional description, chevron. */
export function MenuGroup({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <Box>
      {title && <Text className="menu-group-title">{title}</Text>}
      <Paper withBorder className="menu-list">{children}</Paper>
    </Box>
  );
}

export function MenuRow({ to, onClick, label, description, icon, color = 'gray', danger }: {
  to?: string; onClick?: () => void; label: string; description?: string; icon: ReactNode; color?: string; danger?: boolean;
}) {
  const body = (
    <>
      <span className="menu-icon" style={{ background: `var(--mantine-color-${color}-0)`, color: `var(--mantine-color-${color}-8)` }}>{icon}</span>
      <Box style={{ minWidth: 0, flex: 1 }}>
        <Text fw={600} size="sm" c={danger ? 'red.8' : undefined}>{label}</Text>
        {description && <Text size="xs" c="dimmed" lineClamp={2}>{description}</Text>}
      </Box>
      {to && <IconChevronRight size={18} className="menu-chevron" />}
    </>
  );
  return to
    ? <UnstyledButton component={Link} to={to} className="menu-row">{body}</UnstyledButton>
    : <UnstyledButton onClick={onClick} className="menu-row">{body}</UnstyledButton>;
}
