import { Alert, Anchor, Badge, Box, Button, Checkbox, Group, Loader, Paper, Select, SimpleGrid, Stack, Text, TextInput, Title, UnstyledButton } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { EmptyState } from '../components/CompanyPicker';
import { DateField } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';
import { accountLabel, moneyAccounts, useAccounts } from '../lib/hooks';
import { todayISO } from '../lib/money';

interface Rec {
  id: string; account_id: string; account_name: string; subtype: string; statement_date: string; statement_balance: string;
  status: string; book_balance: string; cleared_balance: string; difference: string; uncleared_in_books: string;
  lines: { id: string; entry_id: string; entry_no: string | null; entry_date: string; description: string; reference_no: string | null; party: string | null; debit: string; credit: string; ticked: boolean }[];
}

export function ReconcileListPage() {
  const { company, can } = useCompany();
  const navigate = useNavigate();
  const accounts = useAccounts();
  const [accountId, setAccountId] = useState<string | null>(null);
  const [date, setDate] = useState(todayISO());
  const [balance, setBalance] = useState('');
  const list = useQuery({
    queryKey: ['recs', company?.id],
    queryFn: () => api<{ id: string; account_name: string; statement_date: string; statement_balance: string; status: string; completed_by_name: string | null }[]>(`/companies/${company!.id}/reconciliations`),
    enabled: !!company,
  });
  const start = useMutation({
    mutationFn: () => api<Rec>(`/companies/${company!.id}/reconciliations`, {
      method: 'POST', body: json({ account_id: accountId, statement_date: date, statement_balance: balance.replace(/[₹,\s]/g, '') }),
    }),
    onSuccess: (r) => navigate(`/reconcile/${r.id}`),
  });
  return (
    <Stack maw={760}>
      <Title order={3}>Reconcile cash &amp; bank</Title>
      <Text size="sm" c="dimmed">Compare the bank statement (or the cash you counted) with the books. Tick each entry that appears on the statement; when the difference is ₹0.00 you can complete it.</Text>
      {can('accountant') && (
        <Paper withBorder p="md">
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <Select label="Account" size="md" value={accountId} onChange={setAccountId}
              data={moneyAccounts(accounts.data).map((a) => ({ value: a.id, label: accountLabel(a) }))} />
            <DateField label="Statement date" value={date} onChange={(e) => setDate(e.currentTarget.value)} />
            <TextInput label="Balance on statement" size="md" inputMode="decimal" leftSection="₹" value={balance}
              onChange={(e) => setBalance(e.currentTarget.value)} />
          </SimpleGrid>
          {start.error && <Alert color="red" mt="sm">{(start.error as ApiError).message}</Alert>}
          <Button mt="sm" disabled={!accountId || !/^-?[\d,]+(\.\d{1,2})?$/.test(balance.replace(/[₹\s]/g, ''))} loading={start.isPending}
            onClick={() => start.mutate()}>Start</Button>
        </Paper>
      )}
      {list.data?.length === 0 && <EmptyState title="No reconciliations yet" />}
      {list.data?.map((r) => (
        <UnstyledButton key={r.id} component={Link} to={`/reconcile/${r.id}`}>
          <Paper withBorder p="sm">
            <Group justify="space-between">
              <Box><Text fw={600}>{r.account_name}</Text><Text size="xs" c="dimmed">Statement {formatDate(r.statement_date)} · {formatINR(r.statement_balance)}{r.completed_by_name ? ` · by ${r.completed_by_name}` : ''}</Text></Box>
              <Badge color={r.status === 'completed' ? 'green' : 'yellow'} variant="light">{r.status === 'completed' ? 'Completed' : 'In progress'}</Badge>
            </Group>
          </Paper>
        </UnstyledButton>
      ))}
    </Stack>
  );
}

export function ReconcilePage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: r, isLoading, error } = useQuery({ queryKey: ['rec', id], queryFn: () => api<Rec>(`/reconciliations/${id}`) });
  const onError = (e: Error) => notifications.show({ color: 'red', message: e.message });
  const tick = useMutation({
    mutationFn: (v: { ids: string[]; cleared: boolean }) => api<Rec>(`/reconciliations/${id}/tick`, { method: 'POST', body: json({ line_ids: v.ids, cleared: v.cleared }) }),
    onSuccess: (d) => qc.setQueryData(['rec', id], d), onError,
  });
  const complete = useMutation({
    mutationFn: () => api<Rec>(`/reconciliations/${id}/complete`, { method: 'POST' }),
    onSuccess: (d) => { qc.setQueryData(['rec', id], d); qc.invalidateQueries({ queryKey: ['recs'] }); qc.invalidateQueries({ queryKey: ['pending'] }); notifications.show({ color: 'green', message: 'Reconciliation completed' }); },
    onError,
  });
  const abandon = useMutation({
    mutationFn: () => api(`/reconciliations/${id}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['recs'] }); navigate('/reconcile'); }, onError,
  });
  if (isLoading) return <Loader />;
  if (error || !r) return <Alert color="red">{(error as Error)?.message ?? 'Not found'}</Alert>;
  const open = r.status === 'in_progress';
  const diffZero = Number(r.difference) === 0;
  return (
    <Stack maw={820}>
      <Anchor component={Link} to="/reconcile" size="sm">← Reconciliations</Anchor>
      <Title order={3}>{r.account_name} · {formatDate(r.statement_date)}</Title>
      <Paper withBorder p="sm" pos="sticky" top={60} style={{ zIndex: 3 }} bg="var(--mantine-color-body)">
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
          <Box><Text size="xs" c="dimmed">Statement</Text><Text fw={700}>{formatINR(r.statement_balance)}</Text></Box>
          <Box><Text size="xs" c="dimmed">Ticked (cleared)</Text><Text fw={700}>{formatINR(r.cleared_balance)}</Text></Box>
          <Box><Text size="xs" c="dimmed">Difference</Text><Text fw={700} c={diffZero ? 'green' : 'red'}>{formatINR(r.difference)}</Text></Box>
          <Box><Text size="xs" c="dimmed">Books</Text><Text fw={700}>{formatINR(r.book_balance)}</Text></Box>
        </SimpleGrid>
        {open && (
          <Group mt="xs" grow>
            <Button variant="default" color="red" onClick={() => abandon.mutate()} loading={abandon.isPending}>Abandon</Button>
            <Button disabled={!diffZero} loading={complete.isPending} onClick={() => complete.mutate()}>{diffZero ? 'Complete' : 'Difference must be ₹0.00'}</Button>
          </Group>
        )}
        {!open && <Badge color="green" mt="xs">Completed — locked</Badge>}
      </Paper>
      {open && r.lines.length > 0 && (
        <Group>
          <Button size="xs" variant="light" onClick={() => tick.mutate({ ids: r.lines.filter((l) => !l.ticked).map((l) => l.id), cleared: true })}>Tick all</Button>
          <Button size="xs" variant="subtle" onClick={() => tick.mutate({ ids: r.lines.filter((l) => l.ticked).map((l) => l.id), cleared: false })}>Untick all</Button>
        </Group>
      )}
      {r.lines.length === 0 && <EmptyState title="Nothing to tick">All entries up to this date are already reconciled.</EmptyState>}
      <Stack gap={6}>
        {r.lines.map((l) => {
          const amount = l.debit !== '0.00' ? l.debit : `-${l.credit}`;
          return (
            <Paper key={l.id} withBorder p="xs">
              <Group wrap="nowrap" gap="sm">
                <Checkbox size="md" checked={l.ticked} disabled={!open || tick.isPending} aria-label={`Cleared: ${l.description}`}
                  onChange={(e) => tick.mutate({ ids: [l.id], cleared: e.currentTarget.checked })} />
                <Box style={{ flex: 1, minWidth: 0 }}>
                  <Text size="sm" truncate>{l.party ?? l.description}</Text>
                  <Text size="xs" c="dimmed">{formatDate(l.entry_date)} · {l.entry_no}{l.reference_no ? ` · ${l.reference_no}` : ''}</Text>
                </Box>
                <Text fw={600} c={amount.startsWith('-') ? 'red.9' : 'teal.9'}>{formatINR(amount)}</Text>
              </Group>
            </Paper>
          );
        })}
      </Stack>
    </Stack>
  );
}
