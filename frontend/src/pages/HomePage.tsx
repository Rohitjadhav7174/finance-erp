import { Alert, Anchor, Badge, Box, Button, Group, Loader, Paper, SegmentedControl, SimpleGrid, Stack, Table, Text, Title, UnstyledButton } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '../components/CompanyPicker';
import { StatusBadge, TYPE_LABEL } from '../components/fields';
import { MoneyFlowChart, type MonthPoint } from '../components/MoneyFlowChart';
import { PeriodPicker, usePeriodDefaults } from '../components/PeriodPicker';
import { useCompany } from '../context/CompanyContext';
import { api } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';
import type { Period } from '../lib/period';

interface Figures {
  opening_cash: string; closing_cash: string; other_movement: string; cash: string; bank: string; money_in: string; money_out: string;
  collected_from_customers: string; income: string; expenses: string; surplus: string; receivables: string;
  payables: string; advances: string; bills_raised: string; supplier_bills: string;
  installments: { overdue: string; overdue_count: number; due_in_period: string; collected_of_due: string; remaining: string; upcoming_30: string };
}
interface Dashboard {
  figures: Figures; monthly: MonthPoint[];
  money_accounts: { id: string; name: string; subtype: string; account_no_last4: string | null; balance: string }[];
  pending: { drafts: number; awaiting_posting: number; approvals: number; missing_reference: number; follow_ups: number };
  recent_entries: { id: string; entry_no: string | null; entry_date: string; entry_type: string; status: string; description: string; party_name: string | null; amount: string }[];
  recent_audit: { at: string; actor: string | null; table_name: string; action: string; ref: string | null; old_status: string | null; new_status: string | null }[];
}

function Tile({ label, value, hint, tone, to }: { label: string; value: string; hint?: React.ReactNode; tone?: string; to?: string }) {
  const body = (
    <Paper withBorder radius="md" p="sm" h="100%">
      <Text size="xs" c="dimmed">{label}</Text>
      <Text fw={700} size="lg" c={tone}>{formatINR(value)}</Text>
      {hint && <Text size="xs" c="dimmed">{hint}</Text>}
    </Paper>
  );
  return to ? <UnstyledButton component={Link} to={to} h="100%">{body}</UnstyledButton> : body;
}

export function HomePage() {
  const { company, me, can } = useCompany();
  const [period, setPeriod] = useState<Period>(usePeriodDefaults('this_fy'));
  const [scope, setScope] = useState('company');
  const consolidatedAllowed = !!me && (me.profile.is_super_admin || me.profile.can_view_consolidated) && me.companies.length > 1;
  if (!company || !me) return null;
  return (
    <Stack>
      <Group justify="space-between" align="flex-end" wrap="wrap" gap="xs">
        <div>
          <Text c="dimmed" size="sm">Namaste, {me.profile.full_name.split(' ')[0]}</Text>
          <Title order={3}>{scope === 'all' ? 'All companies' : company.name}</Title>
        </div>
        <PeriodPicker value={period} onChange={setPeriod} />
      </Group>
      {can('data_entry') && scope === 'company' && (
        <Button component={Link} to="/entry" size="lg" color={company.theme_color} fullWidth>+ Monthly entry</Button>
      )}
      {consolidatedAllowed && (
        <SegmentedControl value={scope} onChange={setScope}
          data={[{ value: 'company', label: company.code }, { value: 'all', label: 'All companies' }]} />
      )}
      {scope === 'all' ? <Consolidated period={period} /> : <CompanyDashboard period={period} />}
    </Stack>
  );
}

function CompanyDashboard({ period }: { period: Period }) {
  const { company, can } = useCompany();
  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard', company?.id, period.from, period.to],
    queryFn: () => api<Dashboard>(`/companies/${company!.id}/dashboard?date_from=${period.from}&date_to=${period.to}`),
    enabled: !!company && !!period.from && !!period.to,
  });
  if (isLoading) return <Loader />;
  if (error || !data) return <Alert color="red">{(error as Error)?.message ?? 'Could not load the dashboard'}</Alert>;
  const f = data.figures;
  const p = data.pending;
  const pendingTotal = p.drafts + p.awaiting_posting + p.approvals + p.missing_reference + f.installments.overdue_count;

  return (
    <Stack>
      <Text size="xs" c="dimmed">{formatDate(period.from)} to {formatDate(period.to)}</Text>

      {/* Position at the end of the period */}
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm">
        <Tile label="Cash & bank balance" value={f.closing_cash} hint={`Cash ${formatINR(f.cash)} · Bank ${formatINR(f.bank)}`} to="/accounts" />
        <Tile label="Customers owe us" value={f.receivables} hint="Unpaid customer bills" to="/bills" />
        <Tile label="We owe suppliers" value={f.payables} hint="Unpaid supplier bills" />
        <Tile label="Overdue installments" value={f.installments.overdue} tone={Number(f.installments.overdue) > 0 ? 'red' : undefined}
          hint={`${f.installments.overdue_count} installment${f.installments.overdue_count === 1 ? '' : 's'}`} to="/pending" />
      </SimpleGrid>

      {pendingTotal > 0 && (
        <Paper withBorder radius="md" p="sm">
          <Group justify="space-between" mb={6}>
            <Text fw={700}>Pending work</Text>
            <Anchor component={Link} to="/pending" size="sm">Open</Anchor>
          </Group>
          <Group gap={6}>
            {f.installments.overdue_count > 0 && <Badge color="red" variant="light">{f.installments.overdue_count} overdue installments</Badge>}
            {p.awaiting_posting > 0 && <Badge color="yellow" variant="light">{p.awaiting_posting} waiting to post</Badge>}
            {p.approvals > 0 && <Badge color="grape" variant="light">{p.approvals} approvals</Badge>}
            {p.drafts > 0 && <Badge color="gray" variant="light">{p.drafts} drafts</Badge>}
            {p.missing_reference > 0 && <Badge color="orange" variant="light">{p.missing_reference} missing receipt no.</Badge>}
          </Group>
        </Paper>
      )}

      {/* Cash movement (what physically moved) */}
      <Paper withBorder radius="md" p="sm">
        <Text fw={700}>Cash movement</Text>
        <Text size="xs" c="dimmed" mb="xs">Money that actually came in or went out of cash and bank. Transfers between your own accounts are not counted.</Text>
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs" mb="sm">
          <Stack gap={0}><Text size="xs" c="dimmed">Opening</Text><Text fw={600}>{formatINR(f.opening_cash)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">Money in</Text><Text fw={600}>{formatINR(f.money_in)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">Money out</Text><Text fw={600}>{formatINR(f.money_out)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">Closing</Text><Text fw={600}>{formatINR(f.closing_cash)}</Text></Stack>
        </SimpleGrid>
        {Number(f.other_movement) !== 0 && (
          <Text size="xs" c="dimmed" mt={-6} mb="sm">
            Includes {formatINR(f.other_movement)} from opening balances &amp; adjustments recorded in this period.
          </Text>
        )}
        <MoneyFlowChart data={data.monthly} />
      </Paper>

      {/* Earnings (accounting) — kept separate from cash on purpose */}
      <Paper withBorder radius="md" p="sm">
        <Text fw={700}>Income &amp; expenses</Text>
        <Text size="xs" c="dimmed" mb="xs">Income is counted when a bill is raised, not when installments are collected.</Text>
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
          <Stack gap={0}><Text size="xs" c="dimmed">Bills raised</Text><Text fw={600}>{formatINR(f.bills_raised)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">Income</Text><Text fw={600}>{formatINR(f.income)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">Expenses</Text><Text fw={600}>{formatINR(f.expenses)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">{Number(f.surplus) >= 0 ? 'Surplus' : 'Deficit'}</Text><Text fw={600}>{formatINR(f.surplus.replace('-', ''))}</Text></Stack>
        </SimpleGrid>
      </Paper>

      <Paper withBorder radius="md" p="sm">
        <Text fw={700} mb="xs">Installments</Text>
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
          <Stack gap={0}><Text size="xs" c="dimmed">Due in period</Text><Text fw={600}>{formatINR(f.installments.due_in_period)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">Collected of that</Text><Text fw={600}>{formatINR(f.installments.collected_of_due)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">Due next 30 days</Text><Text fw={600}>{formatINR(f.installments.upcoming_30)}</Text></Stack>
          <Stack gap={0}><Text size="xs" c="dimmed">Still to collect</Text><Text fw={600}>{formatINR(f.installments.remaining)}</Text></Stack>
        </SimpleGrid>
        {Number(f.advances) > 0 && <Text size="xs" c="dimmed" mt="xs">Customer advances held (not income yet): {formatINR(f.advances)}</Text>}
      </Paper>

      <Paper withBorder radius="md" p="sm">
        <Group justify="space-between" mb="xs"><Text fw={700}>Recent entries</Text><Anchor component={Link} to="/entries" size="sm">All</Anchor></Group>
        {data.recent_entries.length === 0 && <EmptyState title="No entries yet">Tap + to record money received or paid.</EmptyState>}
        {data.recent_entries.map((e) => (
          <UnstyledButton key={e.id} component={Link} to={`/entries/${e.id}`} w="100%">
            <Group justify="space-between" wrap="nowrap" py={4}>
              <Box style={{ minWidth: 0 }}>
                <Text size="sm" truncate>{e.party_name ?? e.description}</Text>
                <Text size="xs" c="dimmed">{TYPE_LABEL[e.entry_type]} · {formatDate(e.entry_date)}</Text>
              </Box>
              <Stack gap={0} align="flex-end">
                <Text size="sm" fw={600}>{formatINR(e.amount)}</Text>
                {e.status !== 'posted' && <StatusBadge status={e.status} />}
              </Stack>
            </Group>
          </UnstyledButton>
        ))}
      </Paper>

      {can('company_admin') && data.recent_audit.length > 0 && (
        <Paper withBorder radius="md" p="sm">
          <Group justify="space-between" mb="xs"><Text fw={700}>Recent activity</Text><Anchor component={Link} to="/reports/audit" size="sm">Audit log</Anchor></Group>
          {data.recent_audit.map((a, i) => (
            <Text key={i} size="xs" c="dimmed">
              {new Date(a.at).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' })} · {a.actor ?? 'system'} ·{' '}
              {a.action === 'insert' ? 'created' : a.old_status !== a.new_status && a.old_status ? `${a.old_status} → ${a.new_status}` : 'changed'}{' '}
              {a.table_name.replace('_', ' ')} {a.ref ?? ''}
            </Text>
          ))}
        </Paper>
      )}
    </Stack>
  );
}

interface ConsolidatedData {
  to: string; note: string; totals: Record<string, string>;
  companies: { company: { id: string; code: string; name: string; theme_color: string }; from: string; figures: Record<string, string> }[];
}

const CONSOLIDATED_ROWS: [string, string][] = [
  ['closing_cash', 'Cash & bank'], ['receivables', 'Customers owe us'], ['payables', 'We owe suppliers'],
  ['overdue_installments', 'Overdue installments'], ['money_in', 'Money in'], ['money_out', 'Money out'],
  ['income', 'Income'], ['expenses', 'Expenses'], ['advances', 'Advances held'],
];

function Consolidated({ period }: { period: Period }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['consolidated', period.from, period.to],
    queryFn: () => api<ConsolidatedData>(`/consolidated?date_from=${period.from}&date_to=${period.to}`),
  });
  if (isLoading) return <Loader />;
  if (error || !data) return <Alert color="red">{(error as Error)?.message}</Alert>;
  return (
    <Paper withBorder radius="md" p="sm">
      <Table.ScrollContainer minWidth={360}>
        <Table fz="sm" striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th />
              {data.companies.map((c) => <Table.Th key={c.company.id} ta="right" c={c.company.theme_color}>{c.company.code}</Table.Th>)}
              <Table.Th ta="right">Total</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {CONSOLIDATED_ROWS.map(([k, label]) => (
              <Table.Tr key={k}>
                <Table.Td>{label}</Table.Td>
                {data.companies.map((c) => <Table.Td key={c.company.id} ta="right">{formatINR(c.figures[k], { symbol: false })}</Table.Td>)}
                <Table.Td ta="right" fw={700}>{formatINR(data.totals[k], { symbol: false })}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Text size="xs" c="dimmed" mt="xs">{data.note}</Text>
    </Paper>
  );
}

export function ComingSoon({ title, phase }: { title: string; phase: string }) {
  return (
    <Stack>
      <Title order={3}>{title}</Title>
      <EmptyState title="Not built yet">This page is part of {phase}.</EmptyState>
    </Stack>
  );
}
