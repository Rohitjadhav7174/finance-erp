import { Alert, Badge, Box, Chip, Group, Loader, Paper, ScrollArea, Select, Stack, Text, TextInput, Title, UnstyledButton } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '../components/CompanyPicker';
import { useCompany } from '../context/CompanyContext';
import { api } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';

interface Item {
  kind: string; kind_label: string; ref_type: 'bill' | 'entry'; ref_id: string; title: string; party: string | null;
  amount: string | null; date: string | null; due_date: string | null; age_days: number | null; created_by: string | null;
  detail: string | null;
}
interface Pending { items: Item[]; total: number; counts: Record<string, number>; labels: Record<string, string>; people: string[] }

// Urgency colours with a text label always alongside (never colour alone).
const TONE: Record<string, string> = {
  overdue_installment: 'red', overdue_bill: 'red', approval_request: 'grape', awaiting_posting: 'yellow',
  upcoming_due: 'blue', unpaid_bill: 'blue', partially_paid_bill: 'orange', draft: 'gray', missing_reference: 'orange',
  missing_due_date: 'orange', unapplied_receipt: 'cyan', unreconciled_bank: 'gray', follow_up: 'teal',
};
const ORDER = Object.keys(TONE);

export function PendingPage() {
  const { company } = useCompany();
  const [kinds, setKinds] = useState<string[]>([]);
  const [sort, setSort] = useState('oldest');
  const [person, setPerson] = useState<string | null>(null);
  const [minAge, setMinAge] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [debounced] = useDebouncedValue(q, 300);

  const { data, isLoading, error } = useQuery({
    queryKey: ['pending', company?.id, kinds, sort, person, minAge, debounced],
    queryFn: () => {
      const p = new URLSearchParams({ sort });
      kinds.forEach((k) => p.append('kind', k));
      if (person) p.set('created_by', person);
      if (minAge) p.set('min_age', minAge);
      if (debounced.trim()) p.set('q', debounced.trim());
      return api<Pending>(`/companies/${company!.id}/pending?${p}`);
    },
    enabled: !!company,
  });

  const kindsPresent = ORDER.filter((k) => data?.counts[k]);
  return (
    <Stack>
      <Title order={3}>Pending work</Title>
      <Text size="sm" c="dimmed">Everything that still needs action — no more searching line by line in Excel.</Text>
      <TextInput type="search" size="md" placeholder="Search party, bill no., amount…" value={q}
        onChange={(e) => setQ(e.currentTarget.value)} aria-label="Search pending items" />
      {kindsPresent.length > 0 && (
        <ScrollArea type="never">
          <Group gap={6} wrap="nowrap">
            <Chip.Group multiple value={kinds} onChange={setKinds}>
              {kindsPresent.map((k) => (
                <Chip key={k} value={k} size="sm" color={TONE[k]}>{data!.labels[k]} · {data!.counts[k]}</Chip>
              ))}
            </Chip.Group>
          </Group>
        </ScrollArea>
      )}
      <Group gap="xs" grow>
        <Select size="sm" aria-label="Sort" value={sort} onChange={(v) => v && setSort(v)} allowDeselect={false}
          data={[{ value: 'oldest', label: 'Oldest first' }, { value: 'due_date', label: 'By due date' }, { value: 'amount', label: 'Largest amount' }]} />
        <Select size="sm" aria-label="Age" placeholder="Any age" clearable value={minAge} onChange={setMinAge}
          data={[{ value: '7', label: 'Older than 7 days' }, { value: '30', label: 'Older than 30 days' }, { value: '90', label: 'Older than 90 days' }]} />
        {(data?.people.length ?? 0) > 0 && (
          <Select size="sm" aria-label="Employee" placeholder="Anyone" clearable value={person} onChange={setPerson}
            data={data!.people} />
        )}
      </Group>

      {isLoading && <Loader />}
      {error && <Alert color="red">{(error as Error).message}</Alert>}
      {data && data.items.length === 0 && (
        <EmptyState title={kinds.length || q || person || minAge ? 'Nothing matches' : 'All clear'}>
          {kinds.length || q || person || minAge ? 'Try removing a filter.' : 'Nothing is waiting for action.'}
        </EmptyState>
      )}
      {data && data.items.length > 0 && <Text size="xs" c="dimmed">{data.total} item{data.total === 1 ? '' : 's'}</Text>}
      <Stack gap="xs">
        {data?.items.map((i, idx) => (
          <UnstyledButton key={`${i.kind}-${i.ref_id}-${idx}`} component={Link}
            to={i.kind === 'approval_request' ? '/approvals' : `/${i.ref_type === 'bill' ? 'bills' : 'entries'}/${i.ref_id}`}>
            <Paper withBorder p="sm" style={{ borderLeft: `4px solid var(--mantine-color-${TONE[i.kind]}-6)` }}>
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                <Box style={{ minWidth: 0 }}>
                  <Badge size="xs" color={TONE[i.kind]} variant="light" mb={4}>{i.kind_label}</Badge>
                  <Text fw={600} size="sm" truncate>{i.party ?? i.title}</Text>
                  {i.party && <Text size="xs" c="dimmed" truncate>{i.title}</Text>}
                  <Text size="xs" c="dimmed">
                    {i.due_date ? `Due ${formatDate(i.due_date)}` : i.date ? formatDate(i.date) : ''}
                    {i.age_days != null && i.age_days > 0 ? ` · ${i.age_days} days old` : ''}
                    {i.created_by ? ` · ${i.created_by}` : ''}
                  </Text>
                </Box>
                {i.amount && <Text fw={700} style={{ flexShrink: 0 }}>{formatINR(i.amount)}</Text>}
              </Group>
            </Paper>
          </UnstyledButton>
        ))}
      </Stack>
    </Stack>
  );
}
