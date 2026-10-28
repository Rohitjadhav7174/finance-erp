import { Alert, Anchor, Box, Button, Center, Chip, Group, Loader, Paper, Progress, ScrollArea, SegmentedControl, Stack, Text, TextInput, Title, UnstyledButton } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { EmptyState } from '../components/CompanyPicker';
import { METHOD_LABEL, StatusBadge } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';
import type { Bill, Page } from '../lib/hooks';
import { toPaise } from '../lib/money';
import { RecordsTabs } from './EntriesPage';

const STATUS_FILTERS = [
  { value: 'overdue', label: 'Overdue' }, { value: 'pending', label: 'Unpaid' }, { value: 'partially_paid', label: 'Part paid' },
  { value: 'paid', label: 'Paid' }, { value: 'draft', label: 'Draft' },
];

const pct = (b: { amount: string; paid: string }) =>
  toPaise(b.amount) > 0n ? Number((toPaise(b.paid) * 100n) / toPaise(b.amount)) : 0;

export function BillsPage() {
  const { company } = useCompany();
  const [direction, setDirection] = useState<'receivable' | 'payable'>('receivable');
  const [statuses, setStatuses] = useState<string[]>([]);
  const [q, setQ] = useState('');
  const [debounced] = useDebouncedValue(q, 300);
  const query = useInfiniteQuery({
    queryKey: ['bills', company?.id, direction, statuses, debounced],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams({ page: String(pageParam), page_size: '25', direction, sort: 'due_date' });
      statuses.forEach((s) => p.append('pay_status', s));
      if (debounced.trim()) p.set('q', debounced.trim());
      return api<Page<Bill>>(`/companies/${company!.id}/bills?${p}`);
    },
    getNextPageParam: (last) => (last.page * last.page_size < last.total ? last.page + 1 : undefined),
    enabled: !!company,
  });
  const rows = query.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Stack>
      <RecordsTabs active="bills" />
      <Title order={3} visibleFrom="sm">Bills</Title>
      <SegmentedControl value={direction} onChange={(v) => setDirection(v as typeof direction)}
        data={[{ value: 'receivable', label: 'Customers owe us' }, { value: 'payable', label: 'We owe suppliers' }]} />
      <TextInput type="search" size="md" placeholder="Search bill no., party…" value={q} onChange={(e) => setQ(e.currentTarget.value)} aria-label="Search bills" />
      <ScrollArea type="never">
        <Group gap={6} wrap="nowrap">
          <Chip.Group multiple value={statuses} onChange={setStatuses}>
            {STATUS_FILTERS.map((f) => <Chip key={f.value} value={f.value} size="sm">{f.label}</Chip>)}
          </Chip.Group>
        </Group>
      </ScrollArea>
      {query.isLoading && <Loader />}
      {query.error && <Alert color="red">{(query.error as Error).message}</Alert>}
      {!query.isLoading && rows.length === 0 && <EmptyState title="No bills">Create one with + → Bill.</EmptyState>}
      <Stack gap="xs">
        {rows.map((b) => (
          <UnstyledButton key={b.id} component={Link} to={`/bills/${b.id}`}>
            <Paper withBorder p="sm">
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                <Box style={{ minWidth: 0 }}>
                  <Text fw={600} truncate>{b.party_name}</Text>
                  <Text size="xs" c="dimmed" truncate>{b.bill_no} · {formatDate(b.bill_date)}{b.due_date ? ` · due ${formatDate(b.due_date)}` : ''}</Text>
                </Box>
                <Box ta="right" style={{ flexShrink: 0 }}>
                  <Text fw={700}>{formatINR(b.outstanding)}</Text>
                  <StatusBadge status={b.pay_status} />
                </Box>
              </Group>
              {b.pay_status !== 'draft' && <Progress value={pct(b)} size="xs" mt="xs" color={b.pay_status === 'overdue' ? 'red' : 'teal'}
                aria-label={`${pct(b)}% paid`} />}
            </Paper>
          </UnstyledButton>
        ))}
      </Stack>
      {query.hasNextPage && <Button variant="light" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>Load more</Button>}
    </Stack>
  );
}

interface BillDetail extends Bill {
  installments: { seq: number; due_date: string; expected_amount: string; paid: string; due: string; status: string }[];
  payments: { entry_id: string; entry_no: string | null; entry_date: string; status: string; payment_method: string | null; reference_no: string | null; amount: string }[];
}

export function BillDetailPage() {
  const { id } = useParams();
  const { can } = useCompany();
  const { data: b, isLoading, error } = useQuery({ queryKey: ['bills', 'detail', id], queryFn: () => api<BillDetail>(`/bills/${id}`) });
  if (isLoading) return <Center h={200}><Loader /></Center>;
  if (error || !b) return <Alert color="red">{(error as Error)?.message ?? 'Not found'}</Alert>;
  const open = ['pending', 'partially_paid', 'overdue'].includes(b.pay_status);
  const payKind = b.direction === 'receivable' ? 'receipt' : 'payment';
  return (
    <Stack maw={720}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div>
          <Text size="sm" c="dimmed">{b.direction === 'receivable' ? 'Customer bill' : 'Supplier bill'} · {b.bill_no}</Text>
          <Title order={3}>{b.party_name}</Title>
        </div>
        <StatusBadge status={b.pay_status} />
      </Group>
      <Paper withBorder p="md">
        <Group grow>
          <Stack gap={0}><Text size="xs" c="dimmed">Bill amount</Text><Text fw={700}>{formatINR(b.amount)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">{b.direction === 'receivable' ? 'Received' : 'Paid'}</Text><Text fw={700} c="teal.9">{formatINR(b.paid)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">Outstanding</Text><Text fw={700} c={b.pay_status === 'overdue' ? 'red' : undefined}>{formatINR(b.outstanding)}</Text></Stack>
        </Group>
        <Progress value={pct(b)} mt="sm" color={b.pay_status === 'overdue' ? 'red' : 'teal'} aria-label={`${pct(b)}% paid`} />
        {toPaise(b.pending_payments) > 0n && (
          <Text size="xs" c="dimmed" mt="xs">{formatINR(b.pending_payments)} more in draft payments, not yet posted.</Text>
        )}
        <Stack gap={4} mt="sm">
          <Text size="sm">Bill date {formatDate(b.bill_date)}{b.due_date ? ` · due ${formatDate(b.due_date)}` : ''}</Text>
          {b.period_from && <Text size="sm">Period {formatDate(b.period_from)} – {formatDate(b.period_to)}</Text>}
          <Text size="sm" c="dimmed">{b.description}</Text>
          <Anchor component={Link} to={`/entries/${b.journal_entry_id}`} size="sm">View accounting entry</Anchor>
        </Stack>
      </Paper>

      {open && can('data_entry') && (
        <Button size="md" component={Link}
          to={`/new/${payKind}?party=${b.party_id}&bill=${b.id}&amount=${b.outstanding}`}>
          {b.direction === 'receivable' ? 'Record money received' : 'Record payment'}
        </Button>
      )}

      {b.installments.length > 0 && (
        <Paper withBorder p="md">
          <Text fw={600} mb="xs">Installments</Text>
          <Stack gap="xs">
            {b.installments.map((i) => (
              <Group key={i.seq} justify="space-between" wrap="nowrap">
                <div>
                  <Text size="sm">{formatDate(i.due_date)}</Text>
                  <Text size="xs" c="dimmed">{formatINR(i.expected_amount)}{i.status !== 'paid' && i.paid !== '0.00' ? ` · ${formatINR(i.due)} left` : ''}</Text>
                </div>
                <StatusBadge status={i.status} />
              </Group>
            ))}
          </Stack>
          <Text size="xs" c="dimmed" mt="xs">Payments are applied to installments in due-date order.</Text>
        </Paper>
      )}

      <Paper withBorder p="md">
        <Text fw={600} mb="xs">Payment history</Text>
        {b.payments.length === 0 && <Text size="sm" c="dimmed">No payments yet.</Text>}
        {b.payments.map((p) => (
          <UnstyledButton key={p.entry_id} component={Link} to={`/entries/${p.entry_id}`} w="100%">
            <Group justify="space-between" wrap="nowrap" py={4}>
              <div>
                <Text size="sm">{formatDate(p.entry_date)} · {p.payment_method ? METHOD_LABEL[p.payment_method] : ''}</Text>
                <Text size="xs" c="dimmed">{p.entry_no ?? 'Draft'}{p.reference_no ? ` · ${p.reference_no}` : ''}</Text>
              </div>
              <Stack gap={0} align="flex-end">
                <Text size="sm" fw={600} td={p.status === 'reversed' ? 'line-through' : undefined}>{formatINR(p.amount)}</Text>
                {p.status !== 'posted' && <StatusBadge status={p.status} />}
              </Stack>
            </Group>
          </UnstyledButton>
        ))}
      </Paper>
    </Stack>
  );
}
