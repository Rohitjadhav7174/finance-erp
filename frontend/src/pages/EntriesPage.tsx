import { Alert, Box, Button, Chip, Group, Loader, Paper, ScrollArea, SegmentedControl, Stack, Text, TextInput, Title, UnstyledButton } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { EmptyState } from '../components/CompanyPicker';
import { StatusBadge, TYPE_LABEL } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';
import type { Page } from '../lib/hooks';

interface EntryRow {
  id: string; entry_no: string | null; entry_date: string; entry_type: string; status: string; description: string;
  reference_no: string | null; party_name: string | null; amount: string; created_by_name: string | null;
}

const TYPE_FILTERS = [
  { value: 'receipt', label: 'Received' }, { value: 'expense', label: 'Expenses' }, { value: 'payment', label: 'Supplier paid' },
  { value: 'bill_sale,bill_purchase', label: 'Bills' }, { value: 'transfer', label: 'Transfers' },
];
const STATUS_FILTERS = [
  { value: 'draft', label: 'Drafts' }, { value: 'pending_approval', label: 'Waiting approval' },
  { value: 'posted', label: 'Posted' }, { value: 'reversed', label: 'Reversed' },
];

const INFLOW = new Set(['receipt']);
const OUTFLOW = new Set(['expense', 'payment']);

export function RecordsTabs({ active }: { active: 'entries' | 'bills' }) {
  const navigate = useNavigate();
  return (
    <SegmentedControl fullWidth value={active} onChange={(v) => navigate(v === 'bills' ? '/bills' : '/entries')}
      data={[{ value: 'entries', label: 'Entries' }, { value: 'bills', label: 'Bills' }]} />
  );
}

export function EntriesPage() {
  const { company } = useCompany();
  const [q, setQ] = useState('');
  const [debounced] = useDebouncedValue(q, 300);
  const [types, setTypes] = useState<string[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);

  const query = useInfiniteQuery({
    queryKey: ['entries', company?.id, debounced, types, statuses],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams({ page: String(pageParam), page_size: '25' });
      if (debounced.trim()) p.set('q', debounced.trim());
      types.flatMap((t) => t.split(',')).forEach((t) => p.append('entry_type', t));
      statuses.forEach((s) => p.append('status', s));
      return api<Page<EntryRow>>(`/companies/${company!.id}/entries?${p}`);
    },
    getNextPageParam: (last) => (last.page * last.page_size < last.total ? last.page + 1 : undefined),
    enabled: !!company,
  });
  const rows = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;

  return (
    <Stack>
      <RecordsTabs active="entries" />
      <Title order={3} visibleFrom="sm">Entries</Title>
      <TextInput size="md" type="search" placeholder="Search party, receipt no., amount, description…"
        value={q} onChange={(e) => setQ(e.currentTarget.value)} aria-label="Search entries" />
      <ScrollArea type="never">
        <Group gap={6} wrap="nowrap">
          <Chip.Group multiple value={types} onChange={setTypes}>
            {TYPE_FILTERS.map((f) => <Chip key={f.value} value={f.value} size="sm">{f.label}</Chip>)}
          </Chip.Group>
        </Group>
      </ScrollArea>
      <ScrollArea type="never">
        <Group gap={6} wrap="nowrap">
          <Chip.Group multiple value={statuses} onChange={setStatuses}>
            {STATUS_FILTERS.map((f) => <Chip key={f.value} value={f.value} size="sm" variant="outline">{f.label}</Chip>)}
          </Chip.Group>
        </Group>
      </ScrollArea>

      {query.isLoading && <Loader />}
      {query.error && <Alert color="red">{(query.error as Error).message}</Alert>}
      {!query.isLoading && rows.length === 0 && (
        <EmptyState title={q || types.length || statuses.length ? 'Nothing matches' : 'No entries yet'}>
          {q || types.length || statuses.length ? 'Try a different search or filter.' : 'Tap + to record money received or paid.'}
        </EmptyState>
      )}
      {rows.length > 0 && <Text size="xs" c="dimmed">{total} entr{total === 1 ? 'y' : 'ies'}</Text>}
      <Stack gap="xs">
        {rows.map((r) => <EntryCard key={r.id} r={r} />)}
      </Stack>
      {query.hasNextPage && (
        <Button variant="light" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>Load more</Button>
      )}
    </Stack>
  );
}

function EntryCard({ r }: { r: EntryRow }) {
  const sign = INFLOW.has(r.entry_type) ? '+' : OUTFLOW.has(r.entry_type) ? '−' : '';
  const color = INFLOW.has(r.entry_type) ? 'teal.9' : OUTFLOW.has(r.entry_type) ? 'red.9' : undefined;
  return (
    <UnstyledButton component={Link} to={`/entries/${r.id}`} aria-label={`${TYPE_LABEL[r.entry_type]} ${formatINR(r.amount)} ${r.party_name ?? ''}`}>
      <Paper withBorder radius="md" p="sm" style={{ opacity: r.status === 'reversed' ? 0.6 : 1 }}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Box style={{ minWidth: 0 }}>
            <Text fw={600} truncate>{r.party_name ?? r.description}</Text>
            <Text size="xs" c="dimmed" truncate>
              {TYPE_LABEL[r.entry_type]} · {formatDate(r.entry_date)}{r.reference_no ? ` · ${r.reference_no}` : ''}
            </Text>
          </Box>
          <Box ta="right" style={{ flexShrink: 0 }}>
            <Text fw={700} c={color} td={r.status === 'reversed' ? 'line-through' : undefined}>{sign}{formatINR(r.amount)}</Text>
            {r.status !== 'posted' && <StatusBadge status={r.status} />}
          </Box>
        </Group>
      </Paper>
    </UnstyledButton>
  );
}
