import { Alert, Badge, Box, Button, Divider, Group, Paper, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput, Textarea, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { AmountInput, DateField, PartySelect } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';
import { accountLabel, byType, moneyAccounts, useAccounts, useParties, useSites } from '../lib/hooks';
import { cleanAmount, fromPaise, isAmount, sumAmounts, todayISO, toPaise } from '../lib/money';

/**
 * ONE form with the same columns as the Excel "Monthly Balance Sheet":
 * Period · Date · Opening Balance · Payments · Monthly Bill · Other Expense / Charge ·
 * Installment Received · Expenses · Cash Balance · Outstanding Bill · Period From · Period To ·
 * Period Shortfall · Status.  Grey columns are calculated, exactly like the Excel formulas.
 */

// Payment categories in the order the Excel sheet uses them; any other expense accounts follow.
const SHEET_ORDER = ['EXP-GDN', 'EXP-DSL', 'EXP-EMP', 'EXP-WRK', 'EXP-OTH'];
const SHEET_LABEL: Record<string, string> = {
  'EXP-GDN': 'Godown Bill', 'EXP-DSL': 'Diesel Payment', 'EXP-EMP': 'Employee Payment',
  'EXP-WRK': 'Worker Payment', 'EXP-OTH': 'Other Expense / Charge',
};

const monthStart = (iso: string) => `${iso.slice(0, 7)}-01`;
const monthEnd = (iso: string) => {
  const [y, m] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
};

function Calc({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <Box p="xs" bg="var(--mantine-color-gray-1)" style={{ borderRadius: 8 }}>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text fw={700} c={tone}>{value}</Text>
    </Box>
  );
}

export function MonthlyEntryPage() {
  const { company, can } = useCompany();
  const qc = useQueryClient();
  const accounts = useAccounts();
  const parties = useParties();
  const sites = useSites();
  const money = moneyAccounts(accounts.data);
  const cash = money.find((a) => a.subtype === 'cash');
  const expenseAccounts = useMemo(() => {
    const list = byType(accounts.data, 'expense');
    return [...list].sort((a, b) => {
      const ia = SHEET_ORDER.indexOf(a.code); const ib = SHEET_ORDER.indexOf(b.code);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  }, [accounts.data]);

  const [date, setDate] = useState(todayISO());
  const [periodFrom, setPeriodFrom] = useState(monthStart(todayISO()));
  const [periodTo, setPeriodTo] = useState(monthEnd(todayISO()));
  const [siteId, setSiteId] = useState<string | null>(null);
  const [partyId, setPartyId] = useState<string | null>(null);
  const [bill, setBill] = useState('');
  const [billNo, setBillNo] = useState('');
  const [received, setReceived] = useState('');
  const [receivedInto, setReceivedInto] = useState<string | null>(null);
  const [receiptMethod, setReceiptMethod] = useState('cash');
  const [receiptNo, setReceiptNo] = useState('');
  const [expenses, setExpenses] = useState<Record<string, string>>({});
  const [paidFrom, setPaidFrom] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID().replace(/-/g, ''));

  useEffect(() => {
    if (cash) { setReceivedInto((v) => v ?? cash.id); setPaidFrom((v) => v ?? cash.id); }
  }, [cash]);

  // Opening balance = cash + bank at the start of the chosen date (from the books)
  const opening = useQuery({
    queryKey: ['opening', company?.id, date],
    queryFn: () => api<{ figures: { opening_cash: string } }>(`/companies/${company!.id}/dashboard?date_from=${date}&date_to=${date}`),
    enabled: !!company && /^\d{4}-\d{2}-\d{2}$/.test(date),
  });
  const openingCash = opening.data?.figures.opening_cash ?? '0';
  const partyOwes = parties.data?.find((p) => p.id === partyId)?.receivable_balance ?? '0';

  const totalExpenses = sumAmounts(Object.values(expenses).filter(isAmount));
  const billP = isAmount(bill) ? toPaise(bill) : 0n;
  const recvP = isAmount(received) ? toPaise(received) : 0n;
  const cashBalance = fromPaise(toPaise(openingCash) + recvP - toPaise(totalExpenses));
  const outstanding = fromPaise(toPaise(partyOwes) + billP - recvP);
  const shortfall = fromPaise(billP > recvP ? billP - recvP : 0n);
  const status = !partyId ? '—' : toPaise(outstanding) <= 0n ? 'Clear' : billP > recvP ? 'Shortfall' : 'Outstanding';

  const save = useMutation({
    mutationFn: (action: 'post' | 'submit' | 'draft') => api<{ entries: { entry_no: string | null; entry_type: string }[] }>(
      `/companies/${company!.id}/monthly-entry`, {
        method: 'POST', idempotencyKey: key,
        body: json({
          entry_date: date, site_id: siteId, party_id: partyId, notes: notes.trim() || null, action,
          monthly_bill: isAmount(bill) ? bill : null, bill_no: billNo.trim() || null,
          period_from: periodFrom || null, period_to: periodTo || null,
          installment_received: isAmount(received) ? received : null, received_into_id: receivedInto,
          receipt_method: receiptMethod, receipt_no: receiptNo.trim() || null,
          expenses: Object.entries(expenses).filter(([, v]) => isAmount(v)).map(([id, v]) => ({
            account_id: id, amount: v,
            label: (() => { const a = expenseAccounts.find((x) => x.id === id); return a ? SHEET_LABEL[a.code] ?? a.name : null; })(),
          })),
          paid_from_id: paidFrom,
          expense_method: money.find((a) => a.id === paidFrom)?.subtype === 'bank' ? 'bank_transfer' : 'cash',
        }),
      }),
    onSuccess: (r, action) => {
      qc.invalidateQueries();
      notifications.show({ color: 'green', title: action === 'post' ? 'Saved & posted' : action === 'submit' ? 'Sent for approval' : 'Draft saved',
        message: `${r.entries.length} entr${r.entries.length === 1 ? 'y' : 'ies'} recorded` });
      setBill(''); setBillNo(''); setReceived(''); setReceiptNo(''); setExpenses({}); setNotes(''); setError(null);
      setKey(crypto.randomUUID().replace(/-/g, ''));
    },
    onError: (e: Error) => setError(e instanceof ApiError ? e.message : 'Not saved. Try again.'),
  });

  const hasAmount = isAmount(bill) || isAmount(received) || Object.values(expenses).some(isAmount);
  const bad = Object.values(expenses).some((v) => v && !isAmount(v)) || (bill && !isAmount(bill)) || (received && !isAmount(received));
  if (!company) return null;

  return (
    <Stack maw={1100}>
      <div>
        <Title order={3}>Monthly entry</Title>
        <Text size="sm" c="dimmed">Same columns as the Excel sheet · recording in <Text span fw={700} c={company.theme_color}>{company.name}</Text>. Grey boxes are calculated.</Text>
      </div>
      {error && <Alert color="red" role="alert">{error}</Alert>}

      <Paper withBorder radius="md" p="md">
        <Text fw={700} mb="sm">1 · Period</Text>
        <SimpleGrid cols={{ base: 2, md: 4 }}>
          <TextInput type="month" label="Period" size="md" value={periodFrom.slice(0, 7)}
            onChange={(e) => { const v = e.currentTarget.value; if (v) { setPeriodFrom(`${v}-01`); setPeriodTo(monthEnd(`${v}-01`)); } }} />
          <DateField label="Date" value={date} onChange={(e) => setDate(e.currentTarget.value)} />
          <DateField label="Period From" value={periodFrom} onChange={(e) => setPeriodFrom(e.currentTarget.value)} />
          <DateField label="Period To" value={periodTo} onChange={(e) => setPeriodTo(e.currentTarget.value)} />
        </SimpleGrid>
        {(sites.data?.length ?? 0) > 0 && (
          <Select mt="sm" label="Site" size="md" clearable maw={300} value={siteId} onChange={setSiteId}
            data={sites.data!.map((s) => ({ value: s.id, label: s.name }))} />
        )}
        <SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm">
          <Calc label="Opening Balance (cash + bank)" value={formatINR(openingCash)} />
        </SimpleGrid>
      </Paper>

      <Paper withBorder radius="md" p="md">
        <Text fw={700} mb="sm">2 · Monthly bill &amp; installment</Text>
        <PartySelect kind="customer" label="Customer" value={partyId} onChange={setPartyId} />
        <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} mt="sm">
          <AmountInput label="Monthly Bill (₹)" value={bill} onChange={(e) => setBill(cleanAmount(e.currentTarget.value))} />
          <TextInput label="Bill / invoice no." size="md" value={billNo} disabled={!isAmount(bill)}
            placeholder={isAmount(bill) ? 'Required' : ''} onChange={(e) => setBillNo(e.currentTarget.value)} />
          <AmountInput label="Installment Received (₹)" value={received} onChange={(e) => setReceived(cleanAmount(e.currentTarget.value))} />
          <TextInput label="Receipt / UTR no." size="md" value={receiptNo} onChange={(e) => setReceiptNo(e.currentTarget.value)} />
        </SimpleGrid>
        {isAmount(received) && (
          <Group mt="sm" align="flex-end" wrap="wrap">
            <Select label="Received into" size="md" w={240} allowDeselect={false} value={receivedInto}
              onChange={(v) => { setReceivedInto(v); setReceiptMethod(money.find((a) => a.id === v)?.subtype === 'bank' ? 'upi' : 'cash'); }}
              data={money.map((a) => ({ value: a.id, label: accountLabel(a) }))} />
            <SegmentedControl value={receiptMethod} onChange={setReceiptMethod}
              data={[{ value: 'cash', label: 'Cash' }, { value: 'upi', label: 'UPI' }, { value: 'bank_transfer', label: 'Bank' }, { value: 'cheque', label: 'Cheque' }]} />
          </Group>
        )}
      </Paper>

      <Paper withBorder radius="md" p="md">
        <Text fw={700} mb="sm">3 · Payments / expenses</Text>
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
          {expenseAccounts.map((a) => (
            <AmountInput key={a.id} label={`${SHEET_LABEL[a.code] ?? a.name} (₹)`} size="md"
              styles={{ input: { fontWeight: 600 } }} value={expenses[a.id] ?? ''}
              onChange={(e) => { const v = cleanAmount(e.currentTarget.value); setExpenses((x) => ({ ...x, [a.id]: v })); }} />
          ))}
        </SimpleGrid>
        {toPaise(totalExpenses) > 0n && (
          <Select mt="sm" label="Paid from" size="md" w={240} allowDeselect={false} value={paidFrom} onChange={setPaidFrom}
            data={money.map((a) => ({ value: a.id, label: accountLabel(a) }))} />
        )}
      </Paper>

      <Paper withBorder radius="md" p="md">
        <Text fw={700} mb="sm">4 · Calculated (like the Excel formulas)</Text>
        <SimpleGrid cols={{ base: 2, md: 5 }}>
          <Calc label="Expenses" value={formatINR(totalExpenses)} />
          <Calc label="Cash Balance" value={formatINR(cashBalance)} tone={toPaise(cashBalance) < 0n ? 'red.9' : undefined} />
          <Calc label="Outstanding Bill" value={formatINR(outstanding)} />
          <Calc label="Period Shortfall" value={formatINR(shortfall)} tone={toPaise(shortfall) > 0n ? 'red.9' : undefined} />
          <Box p="xs" bg="var(--mantine-color-gray-1)" style={{ borderRadius: 8 }}>
            <Text size="xs" c="dimmed">Status</Text>
            <Badge mt={4} color={status === 'Clear' ? 'green' : status === '—' ? 'gray' : 'red'} variant="light">{status}</Badge>
          </Box>
        </SimpleGrid>
        <Text size="xs" c="dimmed" mt="xs">
          Cash balance = opening {formatINR(openingCash)} + received − expenses. Outstanding = what the customer already owed
          {partyId ? ` (${formatINR(partyOwes)})` : ''} + this bill − received. Period {formatDate(periodFrom)} – {formatDate(periodTo)}.
        </Text>
        <Divider my="sm" />
        <Textarea label="Notes (optional)" autosize minRows={1} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
      </Paper>

      <Group grow>
        <Button variant="default" size="md" disabled={!hasAmount || !!bad} loading={save.isPending && save.variables === 'draft'}
          onClick={() => save.mutate('draft')}>Save draft</Button>
        {can('accountant') ? (
          <Button size="md" color={company.theme_color} disabled={!hasAmount || !!bad} loading={save.isPending && save.variables === 'post'}
            onClick={() => save.mutate('post')}>Save</Button>
        ) : (
          <Button size="md" color={company.theme_color} disabled={!hasAmount || !!bad} loading={save.isPending && save.variables === 'submit'}
            onClick={() => save.mutate('submit')}>Send for approval</Button>
        )}
      </Group>
    </Stack>
  );
}
