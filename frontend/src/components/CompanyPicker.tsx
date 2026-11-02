import { Anchor, Box, Paper, Stack, Text, UnstyledButton } from '@mantine/core';
import { useAuth } from '../auth/AuthProvider';
import { useCompany } from '../context/CompanyContext';
import { IconChevronRight } from '../layout/icons';
import { ROLE_LABELS } from '../lib/format';

/** Shown when the user has more than one company: entries always need an explicit company. */
export function CompanyPicker() {
  const { me, selectCompany } = useCompany();
  const { signOut } = useAuth();
  const first = me?.profile.full_name.split(' ')[0];
  return (
    <div className="picker-shell">
      <header className="picker-band">
        <div className="auth-logo"><span aria-hidden="true">₹</span>Finance ERP</div>
        <h1>Namaste{first ? `, ${first}` : ''}</h1>
        <p>Choose the company you want to work in.</p>
      </header>
      <Stack className="picker-list" w="100%" maw={480} gap="sm">
        {me?.companies.map((c) => (
          <UnstyledButton key={c.id} onClick={() => selectCompany(c.id)} aria-label={`Open ${c.name}`}
            className="picker-card" style={{ '--c': c.theme_color } as React.CSSProperties}>
            <span className="picker-code">{c.code}</span>
            <Box style={{ minWidth: 0, flex: 1 }}>
              <Text fw={700} size="lg" lh={1.25}>{c.name}</Text>
              <Text size="sm" c="dimmed">{ROLE_LABELS[c.role]}</Text>
            </Box>
            <IconChevronRight size={20} className="menu-chevron" />
          </UnstyledButton>
        ))}
        <Text size="xs" c="dimmed" ta="center" mt="xs">
          Everything you enter is recorded in the company you choose. You can switch any time from the top bar.
        </Text>
        <Anchor component="button" type="button" size="sm" c="dimmed" mx="auto" onClick={signOut}>Sign out</Anchor>
      </Stack>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <Paper withBorder p="xl" ta="center">
      <Box>
        <Text fw={700}>{title}</Text>
        {children && <Text c="dimmed" size="sm" mt={4}>{children}</Text>}
      </Box>
    </Paper>
  );
}
