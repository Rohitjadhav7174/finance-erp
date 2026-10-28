import { Box, Center, Paper, Stack, Text, Title, UnstyledButton } from '@mantine/core';
import { useCompany } from '../context/CompanyContext';
import { ROLE_LABELS } from '../lib/format';

/** Shown when the user has more than one company: entries always need an explicit company. */
export function CompanyPicker() {
  const { me, selectCompany } = useCompany();
  return (
    <Center mih="100dvh" px="md">
      <Stack w="100%" maw={420}>
        <Title order={3}>Choose a company</Title>
        <Text c="dimmed" size="sm">Everything you enter will be recorded in the company you choose.</Text>
        {me?.companies.map((c) => (
          <UnstyledButton key={c.id} onClick={() => selectCompany(c.id)} aria-label={`Open ${c.name}`}>
            <Paper withBorder p="md" radius="md" style={{ borderLeft: `6px solid ${c.theme_color}` }}>
              <Text fw={700}>{c.name}</Text>
              <Text size="sm" c="dimmed">{ROLE_LABELS[c.role]}</Text>
            </Paper>
          </UnstyledButton>
        ))}
      </Stack>
    </Center>
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
