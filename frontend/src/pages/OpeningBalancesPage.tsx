import { ActionIcon, Alert, Button, Group, Paper, Select, Stack, Text, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AmountInput, DateField, PartySelect } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { formatINR } from '../lib/format';
import { accountLabel, useAccounts, type Account } from '../lib/hooks';
import { cleanAmount, isAmount, sumAmounts } from '../lib/money';
import { presetRange } from '../lib/period';

interface Row { account_id: string | null; party_id: string | null; amount: string }

// What each kind of account normally holds at the start: money we have / are owed = debit; we owe = credit.
const sideFor = (a?: Account) => (a && ['liability', 'equity', 'income'].includes(a.type) ? 'credit' : 'debit');
const needsParty = (a?: Account) => !!a && ['receivable', 'payable', 'customer_advance'].includes(a.subtype);

export function OpeningBalancesPage() {
  const { company, can } = useCompany();
  const accounts = useAccounts();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [date, setDate] = useState(() => presetRange('this_fy', company?.fy_start_month ?? 4).from);
  const [rows, setRows] = useState<Row[]>([{ account_id: null, party_id: null, amount: '' }]);
  const usable = (accounts.data ?? []).filter((a) => a.is_active && a.code !== 'OBE' && ['asset', 'liability'].includes(a.type));
  const byId = (id: string | null) => usable.find((a) => a.id === id);
  const set = (i: number, patch: Partial<Row>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  const debit = sumAmounts(rows.filter((r) => sideFor(byId(r.account_id)) === 'debit').map((r) => r.amount));
  const credit = sumAmounts(rows.filter((r) => sideFor(byId(r.account_id)) === 'credit').map((r) => r.amount));
  const valid = rows.length > 0 && rows.every((r) => r.account_id && isAmount(r.amount) && (!needsParty(byId(r.account_id)) || r.party_id));

  const save = useMutation({
    mutationFn: () => api<{ id: string; entry_no: string }>(`/companies/${company!.id}/entries/opening`, {
      method: 'POST', idempotencyKey: `opening${company!.id.replace(/-/g, '')}${date.replace(/-/g, '')}`,
      body: json({ entry_date: date, description: 'Opening balances', action: 'post',
        balances: rows.map((r) => ({ account_id: r.account_id, party_id: r.party_id, side: sideFor(byId(r.account_id)), amount: r.amount })) }),
    }),
    onSuccess: (e) => {
      qc.invalidateQueries();
      notifications.show({ color: 'green', message: `Opening balances posted (${e.entry_no})` });
      navigate(`/entries/${e.id}`);
    },
  });

  if (!can('company_admin')) return <Alert color="orange">Only a company admin can enter opening balances.</Alert>;
  return (
    <Stack maw={720}>
      <Title order={3}>Opening balances</Title>
      <Text size="sm" c="dimmed">
        Enter what {company?.name} had on the start date: cash in hand, each bank balance, what each customer owed and what you owed each supplier.
        The difference is recorded automatically as opening capital. A second opening entry later needs approval.
      </Text>
      <DateField label="As on date" value={date} onChange={(e) => setDate(e.currentTarget.value)} />
      {rows.map((r, i) => {
        const acc = byId(r.account_id);
        return (
          <Paper key={i} withBorder radius="md" p="sm">
            <Group align="flex-end" wrap="nowrap" gap="xs">
              <Select label="Account" size="md" style={{ flex: 1 }} value={r.account_id} allowDeselect={false}
                data={usable.map((a) => ({ value: a.id, label: accountLabel(a) }))}
                onChange={(v) => set(i, { account_id: v, party_id: null })} />
              <ActionIcon variant="subtle" color="red" size="lg" aria-label={`Remove row ${i + 1}`}
                onClick={() => setRows((x) => x.filter((_, j) => j !== i))}>×</ActionIcon>
            </Group>
            {needsParty(acc) && (
              <PartySelect kind={acc?.subtype === 'payable' ? 'supplier' : 'customer'} label={acc?.subtype === 'payable' ? 'Supplier' : 'Customer'}
                required value={r.party_id} onChange={(v) => set(i, { party_id: v })} />
            )}
            <AmountInput label={acc ? (sideFor(acc) === 'debit' ? 'Amount held / owed to us' : 'Amount we owe') : 'Amount'}
              value={r.amount} onChange={(e) => set(i, { amount: cleanAmount(e.currentTarget.value) })} mt="xs" />
          </Paper>
        );
      })}
      <Button variant="light" onClick={() => setRows((r) => [...r, { account_id: null, party_id: null, amount: '' }])}>+ Add another balance</Button>
      <Paper withBorder radius="md" p="sm">
        <Group justify="space-between"><Text size="sm">We have / are owed</Text><Text fw={600}>{formatINR(debit)}</Text></Group>
        <Group justify="space-between"><Text size="sm">We owe</Text><Text fw={600}>{formatINR(credit)}</Text></Group>
      </Paper>
      {save.error && <Alert color="red">{(save.error as ApiError).message}</Alert>}
      <Button size="md" disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>Post opening balances</Button>
    </Stack>
  );
}
