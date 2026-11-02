import { ActionIcon, Alert, Anchor, Badge, Box, Button, Group, Input, Paper, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { AmountInput, DateField } from '../components/fields';
import { rowPeriod, SavedMonthlyEntries, type SavedRow } from '../components/SavedMonthlyEntries';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { formatINR } from '../lib/format';
import { periodLabel } from '../lib/period';
import { byType, useAccounts, useParties } from '../lib/hooks';
import { cleanAmount, fromPaise, isAmount, sumAmounts, todayISO, toPaise } from '../lib/money';

/**
 * Exactly the 14 columns of the Excel "Monthly Balance Sheet", in the same order:
 * Period · Date · Opening Balance · Payments · Monthly Bill · Other Expense / Charge · Installment Received ·
 * Expenses · Cash Balance · Outstanding Bill · Period From · Period To · Period Shortfall · Status.
 * Grey boxes are calculated like the Excel formulas. Anything the sheet doesn't have
 * (customer, bill no., cash/bank) is filled by the server: Cash in Hand, one standard customer, MB-YYYY-MM.
 */

const PAYMENT_LABEL: Record<string, string> = {
  'EXP-GDN': 'Godown Bill', 'EXP-DSL': 'Diesel Payment', 'EXP-EMP': 'Employee Payment', 'EXP-WRK': 'Worker Payment',
};
const PAYMENT_ORDER = ['EXP-GDN', 'EXP-DSL', 'EXP-EMP', 'EXP-WRK'];
const DEFAULT_CUSTOMER = 'monthly bill customer';

const monthEnd = (iso: string) => {
  const [y, m] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
};

function Calc({ label, value, tone, children }: { label: string; value?: string; tone?: string; children?: React.ReactNode }) {
  return (
    <Box className="calc-box">
      <Text size="xs" c="dimmed" fw={600}>{label}</Text>
      {children ?? <Text fw={800} size="lg" c={tone} className="amount">{value}</Text>}
    </Box>
  );
}

interface PaymentRow { account_id: string | null; amount: string }

export function MonthlyEntryPage() {
  const { company, can } = useCompany();
  const qc = useQueryClient();
  const accounts = useAccounts();
  const parties = useParties();

  const paymentTypes = useMemo(() => {
    const list = byType(accounts.data, 'expense').filter((a) => a.code !== 'EXP-OTH');
    return [...list].sort((a, b) => {
      const ia = PAYMENT_ORDER.indexOf(a.code); const ib = PAYMENT_ORDER.indexOf(b.code);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  }, [accounts.data]);
  const otherExpenseAccount = accounts.data?.find((a) => a.code === 'EXP-OTH');

  const [date, setDate] = useState(todayISO());
  const [periodFrom, setPeriodFrom] = useState(`${todayISO().slice(0, 7)}-01`);
  const [periodTo, setPeriodTo] = useState(monthEnd(todayISO()));
  const [payments, setPayments] = useState<PaymentRow[]>([{ account_id: null, amount: '' }]);
  const [bill, setBill] = useState('');
  const [other, setOther] = useState('');
  const [received, setReceived] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID().replace(/-/g, ''));
  const [tab, setTab] = useState<'new' | 'saved'>('new');
  const [editing, setEditing] = useState<SavedRow | null>(null);

  const resetForm = () => {
    setPayments([{ account_id: null, amount: '' }]); setBill(''); setOther(''); setReceived(''); setError(null);
    setEditing(null); setKey(crypto.randomUUID().replace(/-/g, ''));
  };
  // Edit = open the saved row in the form; saving replaces it (the old row is deleted in the same step).
  const startEdit = (row: SavedRow) => {
    const plain = (v: string | null) => (v ? v.replace(/\.00$/, '') : '');
    const p = rowPeriod(row);
    setDate(row.entry_date); setPeriodFrom(p.from); setPeriodTo(row.period_to ?? monthEnd(p.from));
    setPayments(row.payments.length ? row.payments.map((x) => ({ account_id: x.account_id, amount: plain(x.amount) }))
      : [{ account_id: null, amount: '' }]);
    setBill(plain(row.monthly_bill)); setOther(plain(row.other_expense)); setReceived(plain(row.installment_received));
    setError(null); setEditing(row); setKey(crypto.randomUUID().replace(/-/g, '')); setTab('new');
    window.scrollTo({ top: 0 });
  };

  const opening = useQuery({
    queryKey: ['opening', company?.id, date],
    queryFn: () => api<{ figures: { opening_cash: string } }>(`/companies/${company!.id}/dashboard?date_from=${date}&date_to=${date}`),
    enabled: !!company && /^\d{4}-\d{2}-\d{2}$/.test(date),
  });
  const openingCash = opening.data?.figures.opening_cash ?? '0';
  const owedNow = parties.data?.find((p) => p.name.toLowerCase() === DEFAULT_CUSTOMER)?.receivable_balance ?? '0';
  // While editing, the saved row being replaced must not be counted twice.
  const owedBefore = editing && editing.status === 'posted'
    ? fromPaise(toPaise(owedNow) - toPaise(editing.monthly_bill ?? '0') + toPaise(editing.installment_received ?? '0'))
    : owedNow;

  const filledPayments = payments.filter((p) => p.account_id && isAmount(p.amount));
  const expenses = sumAmounts([...filledPayments.map((p) => p.amount), ...(isAmount(other) ? [other] : [])]);
  const billP = isAmount(bill) ? toPaise(bill) : 0n;
  const recvP = isAmount(received) ? toPaise(received) : 0n;
  const cashBalance = fromPaise(toPaise(openingCash) + recvP - toPaise(expenses));
  const outstanding = fromPaise(toPaise(owedBefore) + billP - recvP);
  const shortfall = fromPaise(billP > recvP ? billP - recvP : 0n);
  const status = toPaise(outstanding) <= 0n ? 'Clear' : billP > recvP ? 'Shortfall' : 'Outstanding';

  const save = useMutation({
    mutationFn: (action: 'post' | 'submit') => api<{ entries: unknown[] }>(`/companies/${company!.id}/monthly-entry`, {
      method: 'POST', idempotencyKey: key,
      body: json({
        entry_date: date, period_from: periodFrom || null, period_to: periodTo || null, action, replaces: editing?.key ?? null,
        monthly_bill: isAmount(bill) ? bill : null,
        installment_received: isAmount(received) ? received : null,
        expenses: [
          ...filledPayments.map((p) => {
            const a = paymentTypes.find((x) => x.id === p.account_id);
            return { account_id: p.account_id, amount: p.amount, label: a ? PAYMENT_LABEL[a.code] ?? a.name : null };
          }),
          ...(isAmount(other) && otherExpenseAccount ? [{ account_id: otherExpenseAccount.id, amount: other, label: 'Other Expense / Charge' }] : []),
        ],
      }),
    }),
    onSuccess: (r, action) => {
      qc.invalidateQueries();
      notifications.show({ color: 'green', title: editing ? 'Changes saved' : action === 'post' ? 'Saved' : 'Sent for approval',
        message: `${r.entries.length} entr${r.entries.length === 1 ? 'y' : 'ies'} recorded` });
      const wasEditing = !!editing;
      resetForm();
      if (wasEditing) setTab('saved');
    },
    onError: (e: Error) => setError(e instanceof ApiError ? e.message : 'Not saved. Try again.'),
  });

  const incomplete = payments.some((p) => (p.amount && !p.account_id) || (p.account_id && p.amount && !isAmount(p.amount)));
  const bad = incomplete || (bill && !isAmount(bill)) || (received && !isAmount(received)) || (other && !isAmount(other));
  const hasAmount = billP > 0n || recvP > 0n || toPaise(expenses) > 0n;
  if (!company) return null;

  return (
    <Stack>
      <div>
        <Anchor component={Link} to="/" size="sm" fw={600}>← Back to dashboard</Anchor>
        <Title order={3}>Monthly entry</Title>
        <Text size="sm" c="dimmed"><Text span fw={700} c={company.theme_color}>{company.name}</Text> · same columns as the Excel sheet · shaded boxes are calculated</Text>
      </div>
      <SegmentedControl value={tab} onChange={(v) => setTab(v as 'new' | 'saved')} maw={420}
        data={[{ value: 'new', label: editing ? 'Edit entry' : 'New entry' }, { value: 'saved', label: 'Saved entries' }]} />
      {tab === 'saved' ? <SavedMonthlyEntries onEdit={startEdit} /> : (<>
      {editing && (
        <Alert color="blue" title={`Editing ${periodLabel(rowPeriod(editing).from, rowPeriod(editing).to)}`}>
          <Group justify="space-between" gap="xs">
            <Text size="sm">Change what you need and save. The old entry is replaced and kept in the history.</Text>
            <Button size="xs" variant="default" onClick={resetForm}>Stop editing</Button>
          </Group>
        </Alert>
      )}
      {error && <Alert color="red" role="alert">{error}</Alert>}

      <div className="entry-grid">
      <Paper withBorder p="md">
        <div className="section-title"><span>1</span>Period</div>
        <Stack gap="sm">
          <Input.Wrapper label="Period" description={<Text span fw={700} c="dark" size="sm">{periodLabel(periodFrom, periodTo)}</Text>}>
            <SimpleGrid cols={{ base: 1, xs: 2 }} mt={6} spacing="xs">
              <TextInput type="month" size="md" label="From month" styles={{ input: { minWidth: 0 } }} value={periodFrom.slice(0, 7)}
                onChange={(e) => { const v = e.currentTarget.value; if (!v) return; setPeriodFrom(`${v}-01`); if (periodTo.slice(0, 7) < v) setPeriodTo(monthEnd(`${v}-01`)); }} />
              <TextInput type="month" size="md" label="To month" styles={{ input: { minWidth: 0 } }} value={periodTo.slice(0, 7)}
                min={periodFrom.slice(0, 7)}
                onChange={(e) => { const v = e.currentTarget.value; if (!v) return; setPeriodTo(monthEnd(`${v}-01`)); if (v < periodFrom.slice(0, 7)) setPeriodFrom(`${v}-01`); }} />
            </SimpleGrid>
          </Input.Wrapper>
          <SimpleGrid cols={{ base: 1, xs: 2 }}>
            <DateField label="Date" value={date} onChange={(e) => setDate(e.currentTarget.value)} />
            <Calc label="Opening Balance (₹)" value={formatINR(openingCash)} />
          </SimpleGrid>
        </Stack>
      </Paper>

      <Paper withBorder p="md">
        <div className="section-title"><span>2</span>Payments</div>
        <Stack gap="xs">
          {payments.map((p, i) => (
            <Group key={i} wrap="nowrap" align="flex-end" gap="xs">
              <Select aria-label={`Payment ${i + 1} type`} placeholder="Godown Bill, Diesel…" size="md" style={{ flex: '1 1 0', minWidth: 0 }}
                rightSection={<></>} rightSectionWidth={8}
                value={p.account_id} allowDeselect={false}
                data={paymentTypes.map((a) => ({ value: a.id, label: PAYMENT_LABEL[a.code] ?? a.name }))}
                onChange={(v) => setPayments((x) => x.map((r, j) => (j === i ? { ...r, account_id: v } : r)))} />
              <AmountInput aria-label={`Payment ${i + 1} amount`} size="md" style={{ flex: '0 0 34%' }} styles={{ input: { fontWeight: 600 } }}
                value={p.amount} onChange={(e) => { const v = cleanAmount(e.currentTarget.value); setPayments((x) => x.map((r, j) => (j === i ? { ...r, amount: v } : r))); }} />
              {payments.length > 1 && (
                <ActionIcon variant="subtle" color="red" size="lg" aria-label={`Remove payment ${i + 1}`}
                  onClick={() => setPayments((x) => x.filter((_, j) => j !== i))}>×</ActionIcon>
              )}
            </Group>
          ))}
          <Button variant="light" size="sm" w="fit-content" onClick={() => setPayments((x) => [...x, { account_id: null, amount: '' }])}>
            + Add payment
          </Button>
        </Stack>
      </Paper>
      </div>

      <div className="entry-grid">
      <Paper withBorder p="md">
        <div className="section-title"><span>3</span>Bill &amp; installment</div>
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <AmountInput label="Monthly Bill (₹)" value={bill} onChange={(e) => setBill(cleanAmount(e.currentTarget.value))} />
          <AmountInput label="Other Expense / Charge (₹)" value={other} onChange={(e) => setOther(cleanAmount(e.currentTarget.value))} />
          <AmountInput label="Installment Received (₹)" value={received} onChange={(e) => setReceived(cleanAmount(e.currentTarget.value))} />
        </SimpleGrid>
      </Paper>

      <Paper withBorder p="md">
        <div className="section-title"><span>4</span>Calculated (like the Excel formulas)</div>
        <SimpleGrid cols={{ base: 1, xs: 2, md: 3 }}>
          <Calc label="Expenses (₹)" value={formatINR(expenses)} />
          <Calc label="Cash Balance (₹)" value={formatINR(cashBalance)} tone={toPaise(cashBalance) < 0n ? 'red.9' : undefined} />
          <Calc label="Outstanding Bill (₹)" value={formatINR(outstanding)} />
          <DateField label="Period From" value={periodFrom} onChange={(e) => setPeriodFrom(e.currentTarget.value)} />
          <DateField label="Period To" value={periodTo} onChange={(e) => setPeriodTo(e.currentTarget.value)} />
          <Calc label="Period Shortfall (₹)" value={formatINR(shortfall)} tone={toPaise(shortfall) > 0n ? 'red.9' : undefined} />
          <Calc label="Status">
            <Badge mt={6} size="lg" variant="filled" color={status === 'Clear' ? '#1e6b30' : '#c92a2a'}>{status}</Badge>
          </Calc>
        </SimpleGrid>
      </Paper>
      </div>

      <div className="save-bar">
      {can('accountant') ? (
        <Button size="lg" fullWidth disabled={!hasAmount || !!bad} loading={save.isPending}
          onClick={() => save.mutate('post')}>{editing ? 'Save changes' : 'Save'}</Button>
      ) : (
        <Button size="lg" fullWidth disabled={!hasAmount || !!bad} loading={save.isPending}
          onClick={() => save.mutate('submit')}>Send for approval</Button>
      )}
      </div>
      </>)}
    </Stack>
  );
}
