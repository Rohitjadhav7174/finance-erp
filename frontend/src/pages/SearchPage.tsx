import { Alert, Badge, Box, Group, Loader, Paper, Stack, Text, TextInput, Title, UnstyledButton } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '../components/CompanyPicker';
import { StatusBadge, TYPE_LABEL } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';

interface Results {
  entries: { id: string; entry_no: string | null; entry_date: string; entry_type: string; status: string; description: string; reference_no: string | null; company_code: string; party_name: string | null; amount: string }[];
  bills: { id: string; bill_no: string; bill_date: string; direction: string; amount: string; status: string; company_code: string; party_name: string }[];
  parties: { id: string; name: string; kind: string; phone: string | null; company_code: string }[];
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (!count) return null;
  return (
    <Stack gap={6}>
      <Text fw={700} size="sm">{title} · {count}</Text>
      {children}
    </Stack>
  );
}

/** Searches every company you can access. Results always show which company they belong to. */
export function SearchPage() {
  const { me, company, selectCompany } = useCompany();
  const [q, setQ] = useState('');
  const [debounced] = useDebouncedValue(q.trim(), 300);
  const { data, isFetching, error } = useQuery({
    queryKey: ['search', debounced],
    queryFn: () => api<Results>(`/search?q=${encodeURIComponent(debounced)}`),
    enabled: debounced.length >= 2,
  });
  const multi = (me?.companies.length ?? 0) > 1;
  // Opening a result from another company switches the active company first, so any edit lands in the right ledger.
  const open = (code: string) => {
    const target = me?.companies.find((c) => c.code === code);
    if (target && target.id !== company?.id) selectCompany(target.id);
  };
  const tag = (code: string) => multi ? <Badge size="xs" variant="outline" color={me?.companies.find((c) => c.code === code)?.theme_color}>{code}</Badge> : null;
  const total = data ? data.entries.length + data.bills.length + data.parties.length : 0;
  return (
    <Stack maw={720}>
      <Title order={3}>Search</Title>
      <TextInput type="search" size="md" autoFocus placeholder="Party, bill no., receipt no., amount, entry ID…" value={q}
        onChange={(e) => setQ(e.currentTarget.value)} aria-label="Search everything" rightSection={isFetching ? <Loader size="xs" /> : null} />
      {error && <Alert color="red">{(error as Error).message}</Alert>}
      {debounced.length >= 2 && data && total === 0 && <EmptyState title="No results">Try fewer words, or the amount without commas.</EmptyState>}
      {data && (
        <Stack>
          <Section title="Entries" count={data.entries.length}>
            {data.entries.map((e) => (
              <UnstyledButton key={e.id} component={Link} to={`/entries/${e.id}`} onClick={() => open(e.company_code)}>
                <Paper withBorder p="sm">
                  <Group justify="space-between" wrap="nowrap">
                    <Box style={{ minWidth: 0 }}>
                      <Group gap={6}>{tag(e.company_code)}<Text size="sm" fw={600} truncate>{e.party_name ?? e.description}</Text></Group>
                      <Text size="xs" c="dimmed" truncate>{TYPE_LABEL[e.entry_type]} · {formatDate(e.entry_date)} · {e.entry_no ?? 'draft'}{e.reference_no ? ` · ${e.reference_no}` : ''}</Text>
                    </Box>
                    <Stack gap={0} align="flex-end"><Text fw={700} size="sm">{formatINR(e.amount)}</Text>{e.status !== 'posted' && <StatusBadge status={e.status} />}</Stack>
                  </Group>
                </Paper>
              </UnstyledButton>
            ))}
          </Section>
          <Section title="Bills" count={data.bills.length}>
            {data.bills.map((b) => (
              <UnstyledButton key={b.id} component={Link} to={`/bills/${b.id}`} onClick={() => open(b.company_code)}>
                <Paper withBorder p="sm">
                  <Group justify="space-between" wrap="nowrap">
                    <Box style={{ minWidth: 0 }}>
                      <Group gap={6}>{tag(b.company_code)}<Text size="sm" fw={600} truncate>{b.party_name}</Text></Group>
                      <Text size="xs" c="dimmed">{b.bill_no} · {formatDate(b.bill_date)} · {b.direction === 'receivable' ? 'customer' : 'supplier'}</Text>
                    </Box>
                    <Text fw={700} size="sm">{formatINR(b.amount)}</Text>
                  </Group>
                </Paper>
              </UnstyledButton>
            ))}
          </Section>
          <Section title="Parties" count={data.parties.length}>
            {data.parties.map((p) => (
              <Paper key={p.id} withBorder p="sm">
                <Group gap={6}>{tag(p.company_code)}<Text size="sm" fw={600}>{p.name}</Text></Group>
                <Text size="xs" c="dimmed">{p.kind}{p.phone ? ` · ${p.phone}` : ''}</Text>
              </Paper>
            ))}
          </Section>
        </Stack>
      )}
    </Stack>
  );
}
