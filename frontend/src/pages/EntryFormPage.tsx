import { ActionIcon, Alert, Anchor, Box, Button, Center, Checkbox, Collapse, Group, Loader, NumberInput, Paper, SegmentedControl, Select, Stack, Text, TextInput, Textarea, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { AccountSelect, AmountInput, DateField, METHOD_OPTIONS, PartySelect } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';
import { accountLabel, byType, moneyAccounts, useAccounts, useOpenBills, useParties, useSites, type Bill } from '../lib/hooks';
import classes from './forms.module.css';
import { addMonths, autoAllocate, cleanAmount, fromPaise, isAmount, splitEqually, sumAmounts, todayISO, toPaise } from '../lib/money';

export type FormKind = 'receipt' | 'expense' | 'payment' | 'transfer' | 'bill';

interface Values {
  receipt_kind: 'customer_payment' | 'advance' | 'other_income';
  direction: 'receivable' | 'payable';
  party_id: string | null;
  amount: string;
  money_account_id: string | null;
  payment_method: string;
  reference_no: string;
  entry_date: string;
  description: string;
  notes: string;
  site_id: string | null;
  income_account_id: string | null;
  expense_account_id: string | null;
  from_account_id: string | null;
  to_account_id: string | null;
  account_id: string | null;
  bill_no: string;
  due_date: string;
  period_from: string;
  period_to: string;
  installments: { due_date: string; expected_amount: string }[];
  allocations: Record<string, string>;
}

const TITLES: Record<FormKind, string> = {
  receipt: 'Money received', expense: 'Expense paid', payment: 'Pay a supplier', transfer: 'Transfer', bill: 'New bill',
};

const blank = (): Values => ({
  receipt_kind: 'customer_payment', direction: 'receivable', party_id: null, amount: '', money_account_id: null,
  payment_method: 'cash', reference_no: '', entry_date: todayISO(), description: '', notes: '', site_id: null,
  income_account_id: null, expense_account_id: null, from_account_id: null, to_account_id: null, account_id: null,
  bill_no: '', due_date: '', period_from: '', period_to: '', installments: [], allocations: {},
});

/** Entry detail payload shape we need here. */
interface EntryDetail { id: string; entry_no: string | null; status: string; version: number; entry_type: string;
  form: (Record<string, unknown> & { kind: FormKind }) | null }

function fromServerForm(f: Record<string, unknown>): Partial<Values> {
  const allocs = (f.allocations as { bill_id: string; amount: string }[] | undefined) ?? [];
  return {
    ...(f as Partial<Values>),
    receipt_kind: (f.receipt_kind as Values['receipt_kind']) ?? 'customer_payment',
    notes: (f.notes as string) ?? '', reference_no: (f.reference_no as string) ?? '',
    due_date: (f.due_date as string) ?? '', period_from: (f.period_from as string) ?? '', period_to: (f.period_to as string) ?? '',
    installments: (f.installments as Values['installments']) ?? [],
    allocations: Object.fromEntries(allocs.map((a) => [a.bill_id, a.amount])),
  };
}

export function EntryFormPage() {
  const params = useParams();
  const editId = params.id;
  const { data: existing, isLoading } = useQuery({
    queryKey: ['entry', editId],
    queryFn: () => api<EntryDetail>(`/entries/${editId}`),
    enabled: !!editId,
  });
  if (editId) {
    if (isLoading) return <Center h={200}><Loader /></Center>;
    if (!existing?.form) return <Alert color="orange">Only drafts can be edited. Posted entries are corrected by reversal.</Alert>;
    return <EntryForm kind={existing.form.kind} existing={existing} />;
  }
  const kind = params.kind as FormKind;
  if (!TITLES[kind]) return <Alert color="red">Unknown entry type.</Alert>;
  return <EntryForm key={kind} kind={kind} />;
}

function EntryForm({ kind, existing }: { kind: FormKind; existing?: EntryDetail }) {
  const { company, can } = useCompany();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [search] = useSearchParams();
  const accounts = useAccounts();
  const parties = useParties();
  const sites = useSites();
  const [v, setV] = useState<Values>(() => ({ ...blank(), ...(existing?.form ? fromServerForm(existing.form) : {}) }));
  const [errors, setErrors] = useState<Partial<Record<keyof Values | 'form', string>>>({});
  const [showMore, setShowMore] = useState(false);
  const [idemKey] = useState(() => crypto.randomUUID().replace(/-/g, ''));
  const set = <K extends keyof Values>(k: K, val: Values[K]) => setV((s) => ({ ...s, [k]: val }));

  const money = moneyAccounts(accounts.data);
  const cash = money.find((a) => a.subtype === 'cash');

  // sensible defaults once accounts load
  useEffect(() => {
    if (!accounts.data || existing) return;
    setV((s) => ({
      ...s,
      money_account_id: s.money_account_id ?? cash?.id ?? null,
      from_account_id: s.from_account_id ?? cash?.id ?? null,
      to_account_id: s.to_account_id ?? money.find((a) => a.subtype === 'bank')?.id ?? null,
      account_id: s.account_id ?? accounts.data!.find((a) => a.code === 'INC-SALE')?.id ?? null,
      income_account_id: s.income_account_id ?? accounts.data!.find((a) => a.code === 'INC-OTH')?.id ?? null,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts.data]);

  // "Record payment" shortcut from a bill: ?party=..&bill=..&amount=..
  useEffect(() => {
    const party = search.get('party');
    const bill = search.get('bill');
    const amount = search.get('amount');
    if (existing || !party) return;
    setV((s) => ({ ...s, party_id: party, amount: amount ?? s.amount, allocations: bill && amount ? { [bill]: amount } : {} }));
  }, [search, existing]);

  const needsBills = (kind === 'receipt' && v.receipt_kind === 'customer_payment') || kind === 'payment';
  const billDirection = kind === 'payment' ? 'payable' : 'receivable';
  const openBills = useOpenBills(needsBills ? v.party_id : null, billDirection);
  const partyName = parties.data?.find((p) => p.id === v.party_id)?.name;

  const save = useMutation({
    mutationFn: (action: 'draft' | 'submit' | 'post') => {
      const body = buildPayload(kind, v, action, partyName, accounts.data?.find((a) => a.id === v.expense_account_id)?.name);
      if (existing) {
        return api<EntryDetail>(`/entries/${existing.id}`, { method: 'PUT', body: json({ ...body, kind, version: existing.version }) });
      }
      return api<EntryDetail>(`/companies/${company!.id}/entries/${kind}`, { method: 'POST', body: json(body), idempotencyKey: idemKey });
    },
    onSuccess: (e) => {
      qc.invalidateQueries({ queryKey: ['entries'] });
      qc.invalidateQueries({ queryKey: ['open-bills'] });
      qc.invalidateQueries({ queryKey: ['bills'] });
      qc.invalidateQueries({ queryKey: ['accounts'] });
      qc.invalidateQueries({ queryKey: ['entry', e.id] });
      const what = e.status === 'posted' ? `Posted ${e.entry_no}` : e.status === 'pending_approval' ? 'Sent for approval' : 'Draft saved';
      notifications.show({ color: 'green', message: what });
      navigate(`/entries/${e.id}`, { replace: true });
    },
    onError: (e: Error) => setErrors({ form: e instanceof ApiError ? e.message : 'Not saved. Try again.' }),
  });

  const submit = (action: 'draft' | 'submit' | 'post') => {
    const errs = validate(kind, v);
    setErrors(errs);
    if (Object.keys(errs).length === 0) save.mutate(action);
    else window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  if (!company) return null;
  const title = kind === 'bill' ? (v.direction === 'receivable' ? 'Bill to customer' : 'Bill from supplier') : TITLES[kind];

  return (
    <Stack gap="md" maw={640}>
      <div>
        <Title order={3}>{existing ? `Edit draft · ${title}` : title}</Title>
        <Text size="sm" c="dimmed">Recording in <Text span fw={700} c={company.theme_color}>{company.name}</Text></Text>
      </div>
      {errors.form && <Alert color="red" role="alert">{errors.form}</Alert>}

      {kind === 'receipt' && (
        <SegmentedControl fullWidth value={v.receipt_kind} onChange={(x) => set('receipt_kind', x as Values['receipt_kind'])}
          disabled={!!existing}
          data={[{ value: 'customer_payment', label: 'Against bill' }, { value: 'advance', label: 'Advance' },
                 { value: 'other_income', label: 'Other income' }]} />
      )}
      {kind === 'bill' && (
        <SegmentedControl fullWidth value={v.direction} disabled={!!existing}
          onChange={(x) => setV((s) => ({ ...s, direction: x as Values['direction'], account_id: null }))}
          data={[{ value: 'receivable', label: 'To customer' }, { value: 'payable', label: 'From supplier' }]} />
      )}

      {(kind !== 'transfer') && (
        <PartySelect
          kind={kind === 'payment' || (kind === 'bill' && v.direction === 'payable') || kind === 'expense' ? 'supplier' : 'customer'}
          label={kind === 'expense' ? 'Paid to (optional)' : kind === 'payment' || (kind === 'bill' && v.direction === 'payable') ? 'Supplier' : 'Customer'}
          required={kind !== 'expense' && !(kind === 'receipt' && v.receipt_kind === 'other_income')}
          value={v.party_id} error={errors.party_id}
          onChange={(id) => setV((s) => ({ ...s, party_id: id, allocations: {} }))} />
      )}

      {kind === 'bill' && (
        <TextInput label="Bill / invoice number" size="md" withAsterisk value={v.bill_no} error={errors.bill_no}
          onChange={(e) => set('bill_no', e.currentTarget.value)} />
      )}

      <AmountInput label={kind === 'bill' ? 'Bill amount' : 'Amount'} withAsterisk value={v.amount} error={errors.amount}
        onChange={(e) => set('amount', cleanAmount(e.currentTarget.value))}
        description={isAmount(v.amount) ? formatINR(v.amount) : undefined} />

      {kind === 'expense' && (
        <AccountSelect label="Expense category" withAsterisk value={v.expense_account_id} error={errors.expense_account_id}
          onChange={(x) => set('expense_account_id', x)}
          data={byType(accounts.data, 'expense').map((a) => ({ value: a.id, label: a.name }))} />
      )}
      {kind === 'bill' && (
        <AccountSelect label={v.direction === 'receivable' ? 'Income type' : 'Expense category'} withAsterisk
          value={v.account_id} error={errors.account_id} onChange={(x) => set('account_id', x)}
          data={byType(accounts.data, v.direction === 'receivable' ? 'income' : 'expense').map((a) => ({ value: a.id, label: a.name }))} />
      )}
      {kind === 'receipt' && v.receipt_kind === 'other_income' && (
        <AccountSelect label="Income type" value={v.income_account_id} error={errors.income_account_id}
          onChange={(x) => set('income_account_id', x)}
          data={byType(accounts.data, 'income').map((a) => ({ value: a.id, label: a.name }))} />
      )}

      {kind === 'transfer' ? (
        <Group grow align="flex-start">
          <AccountSelect label="From" value={v.from_account_id} error={errors.from_account_id}
            onChange={(x) => set('from_account_id', x)} data={money.map((a) => ({ value: a.id, label: accountLabel(a) }))} />
          <AccountSelect label="To" value={v.to_account_id} error={errors.to_account_id}
            onChange={(x) => set('to_account_id', x)} data={money.map((a) => ({ value: a.id, label: accountLabel(a) }))} />
        </Group>
      ) : kind !== 'bill' && (
        <>
          <AccountSelect label={kind === 'receipt' ? 'Received into' : 'Paid from'} value={v.money_account_id}
            error={errors.money_account_id}
            onChange={(x) => {
              const acc = money.find((a) => a.id === x);
              setV((s) => ({ ...s, money_account_id: x, payment_method: acc?.subtype === 'cash' ? 'cash' : s.payment_method === 'cash' ? 'upi' : s.payment_method }));
            }}
            data={money.map((a) => ({ value: a.id, label: accountLabel(a) }))} />
          <SegmentedControl fullWidth value={v.payment_method} onChange={(x) => set('payment_method', x)}
            data={METHOD_OPTIONS.slice(0, 4)} aria-label="Payment method" />
        </>
      )}

      <Group grow align="flex-start">
        <DateField label={kind === 'bill' ? 'Bill date' : 'Date'} value={v.entry_date} error={errors.entry_date}
          onChange={(e) => set('entry_date', e.currentTarget.value)} />
        {kind === 'bill' ? (
          <DateField label="Due date" value={v.due_date} error={errors.due_date}
            onChange={(e) => set('due_date', e.currentTarget.value)} />
        ) : (
          <TextInput size="md" label={kind === 'receipt' ? 'Receipt / UTR no.' : 'Reference no.'} value={v.reference_no}
            onChange={(e) => set('reference_no', e.currentTarget.value)} />
        )}
      </Group>

      {needsBills && v.party_id && isAmount(v.amount) && (
        <AllocationPicker bills={openBills.data?.items ?? []} loading={openBills.isLoading} amount={v.amount}
          value={v.allocations} onChange={(a) => set('allocations', a)} error={errors.allocations}
          kind={kind === 'payment' ? 'payment' : 'receipt'} />
      )}

      {kind === 'bill' && (
        <BillExtras v={v} set={set} errors={errors} />
      )}

      <Anchor component="button" type="button" size="sm" onClick={() => setShowMore((x) => !x)} ta="left">
        {showMore ? 'Hide' : 'Add'} description, notes{(sites.data?.length ?? 0) > 0 ? ', site' : ''}
      </Anchor>
      <Collapse in={showMore || !!errors.description}>
        <Stack>
          <TextInput size="md" label="Description" placeholder="Filled automatically if left empty" value={v.description}
            error={errors.description} onChange={(e) => set('description', e.currentTarget.value)} />
          {(sites.data?.length ?? 0) > 0 && (
            <Select size="md" label="Site" clearable value={v.site_id} onChange={(x) => set('site_id', x)}
              data={sites.data!.map((s) => ({ value: s.id, label: s.name }))} />
          )}
          <Textarea label="Notes" autosize minRows={2} value={v.notes} onChange={(e) => set('notes', e.currentTarget.value)} />
        </Stack>
      </Collapse>

      <Box className={classes.actions}>
        <Group grow wrap="nowrap" className={classes.buttons}>
          <Button variant="default" size="md" loading={save.isPending && save.variables === 'draft'}
            disabled={save.isPending} onClick={() => submit('draft')}>Save draft</Button>
          {can('accountant') ? (
            <Button size="md" color={company.theme_color} loading={save.isPending && save.variables === 'post'}
              disabled={save.isPending} onClick={() => submit('post')}>Save &amp; post</Button>
          ) : (
            <Button size="md" color={company.theme_color} loading={save.isPending && save.variables === 'submit'}
              disabled={save.isPending} onClick={() => submit('submit')}>Send for approval</Button>
          )}
        </Group>
        <Anchor component={Link} to={existing ? `/entries/${existing.id}` : '/'} size="sm" display="block" ta="center" mt="xs">Cancel</Anchor>
      </Box>
    </Stack>
  );
}

function BillExtras({ v, set, errors }: { v: Values; set: <K extends keyof Values>(k: K, val: Values[K]) => void; errors: Partial<Record<string, string>> }) {
  const [count, setCount] = useState<number | string>(v.installments.length || 3);
  const total = sumAmounts(v.installments.map((i) => i.expected_amount));
  const makeSchedule = () => {
    const n = Number(count);
    if (!isAmount(v.amount) || !n || n < 1 || n > 120) return;
    const parts = splitEqually(v.amount, n);
    const first = v.due_date || addMonths(v.entry_date, 1);
    set('installments', parts.map((amt, i) => ({ due_date: addMonths(first, i), expected_amount: amt })));
  };
  return (
    <Paper withBorder p="sm">
      <Stack gap="sm">
        <Text fw={600} size="sm">Service period (optional)</Text>
        <Group grow>
          <DateField label="From" value={v.period_from} onChange={(e) => set('period_from', e.currentTarget.value)} />
          <DateField label="To" value={v.period_to} error={errors.period_to} onChange={(e) => set('period_to', e.currentTarget.value)} />
        </Group>
        <Text fw={600} size="sm">Installments (optional)</Text>
        <Group align="flex-end" wrap="nowrap">
          <NumberInput label="Number of monthly installments" min={1} max={120} value={count} onChange={setCount} size="md" style={{ flex: 1 }} />
          <Button variant="light" size="md" onClick={makeSchedule} disabled={!isAmount(v.amount)}>Create</Button>
        </Group>
        {v.installments.map((inst, i) => (
          <Group key={i} wrap="nowrap" gap="xs" align="flex-end">
            <Text w={24} size="sm" c="dimmed">{i + 1}.</Text>
            <DateField aria-label={`Installment ${i + 1} due date`} style={{ flex: 1 }} value={inst.due_date}
              onChange={(e) => set('installments', v.installments.map((x, j) => (j === i ? { ...x, due_date: e.currentTarget.value } : x)))} />
            <TextInput aria-label={`Installment ${i + 1} amount`} inputMode="decimal" size="md" style={{ flex: 1 }} value={inst.expected_amount}
              onChange={(e) => set('installments', v.installments.map((x, j) => (j === i ? { ...x, expected_amount: cleanAmount(e.currentTarget.value) } : x)))} />
            <ActionIcon variant="subtle" color="red" size="lg" aria-label={`Remove installment ${i + 1}`}
              onClick={() => set('installments', v.installments.filter((_, j) => j !== i))}>×</ActionIcon>
          </Group>
        ))}
        {v.installments.length > 0 && (
          <Text size="sm" c={errors.installments ? 'red' : 'dimmed'}>
            Total of installments {formatINR(total)}{isAmount(v.amount) && ` of ${formatINR(v.amount)}`}
            {errors.installments && ` — ${errors.installments}`}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}

function AllocationPicker({ bills, loading, amount, value, onChange, error, kind }: {
  bills: Bill[]; loading: boolean; amount: string; value: Record<string, string>;
  onChange: (v: Record<string, string>) => void; error?: string; kind: 'receipt' | 'payment';
}) {
  const allocated = sumAmounts(Object.values(value));
  const left = fromPaise(toPaise(amount) - toPaise(allocated));
  const sorted = useMemo(() => bills.filter((b) => b.status === 'posted'), [bills]);
  return (
    <Paper withBorder p="sm">
      <Group justify="space-between" mb="xs">
        <Text fw={600} size="sm">Apply to bills</Text>
        {sorted.length > 0 && (
          <Button size="xs" variant="light" onClick={() => onChange(autoAllocate(amount, sorted))}>Oldest first</Button>
        )}
      </Group>
      {loading && <Loader size="sm" />}
      {!loading && sorted.length === 0 && <Text size="sm" c="dimmed">No unpaid bills for this party.</Text>}
      <Stack gap="xs">
        {sorted.map((b) => {
          const on = b.id in value;
          return (
            <Group key={b.id} wrap="nowrap" align="center" gap="xs">
              <Checkbox checked={on} aria-label={`Apply to bill ${b.bill_no}`}
                onChange={(e) => {
                  const next = { ...value };
                  if (e.currentTarget.checked) {
                    const room = toPaise(amount) - toPaise(allocated);
                    const take = room < toPaise(b.outstanding) ? room : toPaise(b.outstanding);
                    next[b.id] = fromPaise(take > 0n ? take : 0n);
                  } else delete next[b.id];
                  onChange(next);
                }} />
              <Box style={{ flex: 1, minWidth: 0 }}>
                <Text size="sm" fw={600} truncate>{b.bill_no}</Text>
                <Text size="xs" c="dimmed">{formatDate(b.bill_date)} · due {formatINR(b.outstanding)}</Text>
              </Box>
              {on && (
                <TextInput w={120} inputMode="decimal" aria-label={`Amount for bill ${b.bill_no}`} value={value[b.id]}
                  onChange={(e) => onChange({ ...value, [b.id]: cleanAmount(e.currentTarget.value) })} />
              )}
            </Group>
          );
        })}
      </Stack>
      {error && <Text c="red" size="sm" mt="xs">{error}</Text>}
      {sorted.length > 0 && toPaise(left) > 0n && (
        <Text size="xs" c="dimmed" mt="xs">
          {formatINR(left)} not applied to a bill — it stays as {kind === 'receipt' ? 'an on-account credit for this customer' : 'an advance to this supplier'}.
        </Text>
      )}
    </Paper>
  );
}

// ---------------------------------------------------------------------------
function validate(kind: FormKind, v: Values): Partial<Record<keyof Values | 'form', string>> {
  const e: Partial<Record<keyof Values | 'form', string>> = {};
  if (!isAmount(v.amount)) e.amount = 'Enter an amount greater than 0 (max 2 decimals)';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v.entry_date)) e.entry_date = 'Choose a date';
  const partyRequired = kind === 'bill' || kind === 'payment' || (kind === 'receipt' && v.receipt_kind !== 'other_income');
  if (partyRequired && !v.party_id) e.party_id = 'Choose the party';
  if (kind !== 'bill' && kind !== 'transfer' && !v.money_account_id) e.money_account_id = 'Choose cash or bank account';
  if (kind === 'expense' && !v.expense_account_id) e.expense_account_id = 'Choose a category';
  if (kind === 'bill') {
    if (!v.bill_no.trim()) e.bill_no = 'Enter the bill number';
    if (!v.account_id) e.account_id = 'Choose a category';
    if (v.due_date && v.due_date < v.entry_date) e.due_date = 'Due date is before the bill date';
    if (v.period_from && v.period_to && v.period_to < v.period_from) e.period_to = 'Ends before it starts';
    if (v.installments.some((i) => !isAmount(i.expected_amount) || !i.due_date)) e.installments = 'check each installment';
    else if (toPaise(sumAmounts(v.installments.map((i) => i.expected_amount))) > toPaise(v.amount)) e.installments = 'more than the bill amount';
  }
  if (kind === 'transfer' && (!v.from_account_id || !v.to_account_id || v.from_account_id === v.to_account_id)) {
    e.to_account_id = 'Choose two different accounts';
  }
  if (kind === 'receipt' && v.receipt_kind === 'other_income' && !v.income_account_id) e.income_account_id = 'Choose income type';
  const allocTotal = toPaise(sumAmounts(Object.values(v.allocations)));
  if (Object.values(v.allocations).some((a) => !isAmount(a))) e.allocations = 'Each bill amount must be greater than 0';
  else if (allocTotal > toPaise(v.amount)) e.allocations = 'More applied to bills than the amount';
  return e;
}

function buildPayload(kind: FormKind, v: Values, action: string, partyName?: string, expenseName?: string) {
  const ref = v.reference_no.trim() || null;
  const autoDesc = {
    receipt: v.receipt_kind === 'other_income' ? 'Other income received' : `Received from ${partyName ?? 'customer'}`,
    expense: `${expenseName ?? 'Expense'}${partyName ? ` — ${partyName}` : ''}`,
    payment: `Paid to ${partyName ?? 'supplier'}`,
    transfer: 'Transfer between accounts',
    bill: `${v.direction === 'receivable' ? 'Bill to' : 'Bill from'} ${partyName ?? ''} ${v.bill_no}`.trim(),
  }[kind];
  const common = {
    entry_date: v.entry_date, description: v.description.trim() || autoDesc, notes: v.notes.trim() || null,
    site_id: v.site_id, action,
  };
  const allocations = Object.entries(v.allocations).map(([bill_id, amount]) => ({ bill_id, amount }));
  switch (kind) {
    case 'receipt':
      return { ...common, receipt_kind: v.receipt_kind, party_id: v.party_id, amount: v.amount, money_account_id: v.money_account_id,
        payment_method: v.payment_method, reference_no: ref,
        income_account_id: v.receipt_kind === 'other_income' ? v.income_account_id : null,
        allocations: v.receipt_kind === 'customer_payment' ? allocations : [] };
    case 'expense':
      return { ...common, expense_account_id: v.expense_account_id, amount: v.amount, money_account_id: v.money_account_id,
        payment_method: v.payment_method, party_id: v.party_id, reference_no: ref };
    case 'payment':
      return { ...common, party_id: v.party_id, amount: v.amount, money_account_id: v.money_account_id,
        payment_method: v.payment_method, reference_no: ref, allocations };
    case 'transfer':
      return { ...common, from_account_id: v.from_account_id, to_account_id: v.to_account_id, amount: v.amount,
        payment_method: 'bank_transfer', reference_no: ref };
    case 'bill':
      return { ...common, direction: v.direction, bill_no: v.bill_no.trim(), party_id: v.party_id, amount: v.amount,
        account_id: v.account_id, due_date: v.due_date || null, period_from: v.period_from || null,
        period_to: v.period_to || null, installments: v.installments };
  }
}
