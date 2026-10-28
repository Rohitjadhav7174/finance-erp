import { Alert, Anchor, Badge, Box, Button, Group, Loader, Paper, Select, SimpleGrid, Stack, Table, Text, Title, UnstyledButton } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { EmptyState } from '../components/CompanyPicker';
import { StatusBadge } from '../components/fields';
import { PeriodPicker, usePeriodDefaults } from '../components/PeriodPicker';
import { useCompany } from '../context/CompanyContext';
import { api, download } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';
import { accountLabel, useAccounts } from '../lib/hooks';
import type { Period } from '../lib/period';
import classes from './reports.module.css';

interface ReportMeta { key: string; title: string; hint: string; admin?: boolean; asOf?: boolean }

const GROUPS: { title: string; reports: ReportMeta[] }[] = [
  { title: 'Balances', reports: [
    { key: 'monthly_balance_sheet', title: 'Monthly balance sheet', hint: 'Month by month: opening, bills, installments, expenses, closing, shortfall' },
    { key: 'income_expense', title: 'Income & expense', hint: 'Earnings and spending by category' },
  ] },
  { title: 'Books', reports: [
    { key: 'cash_book', title: 'Daily cash book', hint: 'Every cash receipt and payment with running balance' },
    { key: 'bank_book', title: 'Bank book', hint: 'Every bank movement with running balance' },
    { key: 'transaction_register', title: 'Transaction register', hint: 'All entries with status and who entered them' },
  ] },
  { title: 'Customers & suppliers', reports: [
    { key: 'receivables', title: 'Receivables', hint: 'Who owes us, by age', asOf: true },
    { key: 'payables', title: 'Payables', hint: 'Whom we owe, by age', asOf: true },
    { key: 'bill_register', title: 'Bill register', hint: 'All bills with paid and outstanding' },
    { key: 'installments', title: 'Installments', hint: 'Collected and outstanding installments by due date' },
  ] },
  { title: 'Control', reports: [
    { key: 'pending_work', title: 'Pending work', hint: 'Everything that still needs action' },
    { key: 'audit', title: 'Audit & approvals', hint: 'Who changed what, and when', admin: true },
  ] },
];
const ALL = Object.fromEntries(GROUPS.flatMap((g) => g.reports).map((r) => [r.key, r]));

export function ReportsPage() {
  const { can } = useCompany();
  return (
    <Stack maw={900}>
      <Title order={3}>Reports</Title>
      {GROUPS.map((g) => (
        <Stack key={g.title} gap="xs">
          <Text fw={700} size="sm" c="dimmed">{g.title}</Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
            {g.reports.filter((r) => !r.admin || can('company_admin')).map((r) => (
              <UnstyledButton key={r.key} component={Link} to={`/reports/${r.key}`}>
                <Paper withBorder p="sm" h="100%">
                  <Text fw={600}>{r.title}</Text>
                  <Text size="xs" c="dimmed">{r.hint}</Text>
                </Paper>
              </UnstyledButton>
            ))}
          </SimpleGrid>
        </Stack>
      ))}
      <Text size="xs" c="dimmed">Every report shows only the company you are in and the dates you choose. Download as Excel or CSV, or print / save as PDF.</Text>
    </Stack>
  );
}

interface Column { key: string; label: string; type: 'text' | 'money' | 'date' | 'number' }
interface Report {
  title: string; from: string; to: string; columns: Column[]; rows: Record<string, string | number | null>[];
  totals: Record<string, string | null>; notes: string[]; company: { name: string; code: string }; generated_by: string | null;
}

const STATUS_KEYS = new Set(['pending', 'partially_paid', 'overdue', 'paid', 'upcoming', 'draft', 'pending_approval', 'posted', 'reversed']);

function Cell({ c, v }: { c: Column; v: string | number | null | undefined }) {
  if (v === null || v === undefined || v === '') return null;
  if (c.type === 'money') return <>{formatINR(String(v), { symbol: false })}</>;
  if (c.type === 'date') return <>{formatDate(String(v))}</>;
  if (c.key === 'status' && STATUS_KEYS.has(String(v))) return <StatusBadge status={String(v)} />;
  return <>{String(v)}</>;
}

export function ReportViewPage({ fixedName }: { fixedName?: string } = {}) {
  const routeParams = useParams();
  const name = fixedName ?? routeParams.name ?? "";
  const meta = ALL[name];
  const { company } = useCompany();
  const accounts = useAccounts();
  const [period, setPeriod] = useState<Period>(usePeriodDefaults(name === 'cash_book' || name === 'bank_book' ? 'this_month' : 'this_fy'));
  const [accountId, setAccountId] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const phone = useMediaQuery('(max-width: 48em)');

  const params = new URLSearchParams({ date_from: period.from, date_to: period.to });
  if (accountId) params.set('account_id', accountId);
  const path = `/companies/${company?.id}/reports/${name}?${params}`;
  const { data, isLoading, error } = useQuery({
    queryKey: ['report', company?.id, name, period.from, period.to, accountId],
    queryFn: () => api<Report>(path),
    enabled: !!company && !!meta && !!period.from && !!period.to,
  });

  if (!meta) return <Alert color="red">Unknown report.</Alert>;
  const bookSubtype = name === 'cash_book' ? 'cash' : name === 'bank_book' ? 'bank' : null;

  const save = async (format: 'xlsx' | 'csv') => {
    setDownloading(format);
    try {
      await download(`${path}&format=${format}`, `${name}.${format}`);
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    } finally {
      setDownloading(null);
    }
  };

  return (
    <Stack className={classes.report}>
      {!fixedName && <Anchor component={Link} to="/reports" size="sm" className={classes.noPrint}>← All reports</Anchor>}
      <div>
        <Text size="sm" c="dimmed" className={classes.printOnly}>{data?.company.name}</Text>
        <Title order={3}>{meta.title}</Title>
        <Text size="sm" c="dimmed">{meta.asOf ? `As of ${formatDate(period.to)}` : `${formatDate(period.from)} to ${formatDate(period.to)}`}</Text>
      </div>
      <Group justify="space-between" wrap="wrap" gap="xs" className={classes.noPrint}>
        <Group gap="xs" wrap="wrap">
          <PeriodPicker value={period} onChange={setPeriod} />
          {bookSubtype && (
            <Select size="sm" w={200} placeholder={`All ${bookSubtype} accounts`} clearable value={accountId} onChange={setAccountId}
              aria-label="Account"
              data={(accounts.data ?? []).filter((a) => a.subtype === bookSubtype).map((a) => ({ value: a.id, label: accountLabel(a) }))} />
          )}
        </Group>
        <Group gap="xs">
          <Button size="sm" variant="light" loading={downloading === 'xlsx'} disabled={!data} onClick={() => save('xlsx')}>Excel</Button>
          <Button size="sm" variant="light" loading={downloading === 'csv'} disabled={!data} onClick={() => save('csv')}>CSV</Button>
          <Button size="sm" variant="default" disabled={!data} onClick={() => window.print()}>Print / PDF</Button>
        </Group>
      </Group>

      {isLoading && <Loader />}
      {error && <Alert color="red">{(error as Error).message}</Alert>}
      {data && data.rows.length === 0 && <EmptyState title="Nothing in this period">Choose different dates.</EmptyState>}
      {data && data.rows.length > 0 && phone && <ReportCards data={data} />}
      {data && data.rows.length > 0 && (
        <Paper withBorder className={`${classes.tableWrap} ${phone ? classes.printOnly : ''}`}>
          <Table.ScrollContainer minWidth={Math.max(360, data.columns.length * 110)}>
            <Table fz="xs" striped stickyHeader verticalSpacing={6} className={classes.table}>
              <Table.Thead>
                <Table.Tr>
                  {data.columns.map((c) => <Table.Th key={c.key} ta={c.type === 'money' || c.type === 'number' ? 'right' : 'left'}>{c.label}</Table.Th>)}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.rows.map((r, i) => (
                  <Table.Tr key={i} c={r.status === 'reversed' ? 'dimmed' : undefined}>
                    {data.columns.map((c) => (
                      <Table.Td key={c.key} ta={c.type === 'money' || c.type === 'number' ? 'right' : 'left'}
                        style={{ whiteSpace: c.type === 'text' && c.key !== 'payments_particulars' && c.key !== 'description' ? 'nowrap' : undefined }}>
                        {c.key === 'entry_no' && r.entry_id ? (
                          <Anchor component={Link} to={`/entries/${r.entry_id}`} size="xs">{String(r[c.key] ?? '')}</Anchor>
                        ) : c.key === 'bill_no' && r.bill_id ? (
                          <Anchor component={Link} to={`/bills/${r.bill_id}`} size="xs">{String(r[c.key])}</Anchor>
                        ) : <Cell c={c} v={r[c.key]} />}
                      </Table.Td>
                    ))}
                  </Table.Tr>
                ))}
              </Table.Tbody>
              {Object.values(data.totals).some((v) => v) && (
                <Table.Tfoot>
                  <Table.Tr fw={700}>
                    {data.columns.map((c, i) => (
                      <Table.Td key={c.key} ta={c.type === 'money' ? 'right' : 'left'}>
                        {i === 0 ? 'Total' : c.type === 'money' && data.totals[c.key] ? formatINR(data.totals[c.key]!, { symbol: false }) : ''}
                      </Table.Td>
                    ))}
                  </Table.Tr>
                </Table.Tfoot>
              )}
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {data && (
        <Box>
          {data.notes.map((n, i) => <Text key={i} size="xs" c="dimmed">{n}</Text>)}
          <Text size="xs" c="dimmed" className={classes.printOnly}>
            Generated {new Date().toLocaleString('en-IN')} by {data.generated_by} · {data.rows.length} rows
          </Text>
        </Box>
      )}
    </Stack>
  );
}

const linkFor = (r: Record<string, string | number | null>) =>
  r.entry_id ? `/entries/${r.entry_id}` : r.bill_id ? `/bills/${r.bill_id}` : null;

/** Phone layout: one card per row, label/value pairs, empty values hidden. Printing still uses the table. */
const SHEET_STATUS: Record<string, string> = { Clear: 'green', Outstanding: 'orange', Shortfall: 'red', 'No activity': 'gray' };
const isZero = (c: Column, v: unknown) => c.type === 'money' && /^-?0(\.0+)?$/.test(String(v));
const CARD_FIELDS = 5;
// Most useful figures first on phone cards; then other amounts; text last.
const PRIORITY = ['bills_raised', 'installments_received', 'expenses', 'closing', 'outstanding_bill', 'shortfall',
  'amount', 'receipt', 'payment', 'balance', 'outstanding', 'paid', 'remaining'];
const rank = (c: Column) => {
  const i = PRIORITY.indexOf(c.key);
  return i >= 0 ? i : c.type === 'money' ? 50 : c.type === 'date' ? 60 : 70;
};

function ReportCard({ data, r }: { data: Report; r: Record<string, string | number | null> }) {
  const [open, setOpen] = useState(false);
  const [first, ...rest] = data.columns;
  const statusCol = rest.find((c) => c.key === 'status');
  const fields = rest.filter((c) => c !== statusCol && r[c.key] !== null && r[c.key] !== undefined && r[c.key] !== '' && !isZero(c, r[c.key]))
    .sort((a, b) => rank(a) - rank(b));
  const shown = open ? fields : fields.slice(0, CARD_FIELDS);
  const status = statusCol ? String(r[statusCol.key] ?? '') : '';
  return (
    <Paper withBorder p="sm" c={r.status === 'reversed' ? 'dimmed' : undefined}>
      <Group justify="space-between" wrap="nowrap" mb={6}>
        <Text fw={800} size="sm"><Cell c={first} v={r[first.key]} /></Text>
        {status && (SHEET_STATUS[status]
          ? <Badge variant="light" color={SHEET_STATUS[status]}>{status}</Badge>
          : <Cell c={statusCol!} v={status} />)}
      </Group>
      <Stack gap={4}>
        {shown.map((c) => (
          <Group key={c.key} justify="space-between" wrap="nowrap" gap="md" align="flex-start">
            <Text size="xs" c="dimmed" style={{ flexShrink: 0, maxWidth: '55%' }}>{c.label}</Text>
            <Text size="sm" ta="right" fw={c.type === 'money' ? 700 : undefined} className="amount">
              <Cell c={c} v={r[c.key]} />
            </Text>
          </Group>
        ))}
      </Stack>
      {fields.length > CARD_FIELDS && (
        <Anchor component="button" type="button" size="xs" mt={6}
          onClick={(e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); setOpen((o) => !o); }}>
          {open ? 'Show less' : `Show all (${fields.length - CARD_FIELDS} more)`}
        </Anchor>
      )}
    </Paper>
  );
}

/** Phone layout: one compact card per row; zero amounts hidden. Printing still uses the full table. */
function ReportCards({ data }: { data: Report }) {
  const rest = data.columns.slice(1);
  const moneyTotals = rest.filter((c) => c.type === 'money' && data.totals[c.key] && !isZero(c, data.totals[c.key]));
  return (
    <Stack gap="sm" className={classes.noPrint}>
      {data.rows.map((r, i) => {
        const to = linkFor(r);
        const card = <ReportCard data={data} r={r} />;
        return to ? <UnstyledButton key={i} component={Link} to={to} style={{ display: 'block' }}>{card}</UnstyledButton> : <Box key={i}>{card}</Box>;
      })}
      {moneyTotals.length > 0 && (
        <Paper withBorder p="sm" style={{ borderColor: 'var(--company-color)', borderWidth: 2 }}>
          <Text fw={800} size="sm" mb={6}>Total</Text>
          <Stack gap={4}>
            {moneyTotals.map((c) => (
              <Group key={c.key} justify="space-between" wrap="nowrap"><Text size="xs" c="dimmed">{c.label}</Text>
                <Text size="sm" fw={800} className="amount">{formatINR(data.totals[c.key]!, { symbol: false })}</Text></Group>
            ))}
          </Stack>
        </Paper>
      )}
      <Text size="xs" c="dimmed">Zero amounts are hidden on phones. Rotate to landscape or print to see every column.</Text>
    </Stack>
  );
}
