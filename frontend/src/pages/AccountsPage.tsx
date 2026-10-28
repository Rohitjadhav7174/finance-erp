import { Alert, Button, Group, Paper, SegmentedControl, Stack, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { formatINR } from '../lib/format';
import { accountLabel, useAccounts, type Account } from '../lib/hooks';

const GROUPS: { title: string; hint: string; match: (a: Account) => boolean; balanceSign: 1 | -1 }[] = [
  { title: 'Cash & bank', hint: 'Money the company holds', match: (a) => ['cash', 'bank'].includes(a.subtype), balanceSign: 1 },
  { title: 'Income types', hint: 'Earned this way', match: (a) => a.type === 'income', balanceSign: -1 },
  { title: 'Expense categories', hint: 'Spent this way', match: (a) => a.type === 'expense', balanceSign: 1 },
];

export function AccountsPage() {
  const { company, can } = useCompany();
  const { data } = useAccounts();
  return (
    <Stack maw={720}>
      <Title order={3}>Accounts &amp; categories</Title>
      {GROUPS.map((g) => (
        <Paper key={g.title} withBorder radius="md" p="md">
          <Text fw={700}>{g.title}</Text>
          <Text size="xs" c="dimmed" mb="xs">{g.hint}</Text>
          {(data ?? []).filter(g.match).map((a) => (
            <Group key={a.id} justify="space-between" py={2} wrap="nowrap">
              <Text size="sm" c={a.is_active ? undefined : 'dimmed'} truncate>{accountLabel(a)}</Text>
              <Text size="sm" fw={600}>{formatINR(g.balanceSign === 1 ? a.balance : a.balance.startsWith('-') ? a.balance.slice(1) : `-${a.balance}`)}</Text>
            </Group>
          ))}
        </Paper>
      ))}
      <Text size="xs" c="dimmed">Totals include posted entries of all dates.</Text>
      {can('accountant') && company && <NewAccount companyId={company.id} />}
    </Stack>
  );
}

function NewAccount({ companyId }: { companyId: string }) {
  const qc = useQueryClient();
  const [kind, setKind] = useState('bank');
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [last4, setLast4] = useState('');
  const m = useMutation({
    mutationFn: () => api(`/companies/${companyId}/accounts`, {
      method: 'POST', body: json({ kind, name: name.trim(), code: code.trim(), account_no_last4: kind === 'bank' && last4 ? last4 : null }),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['accounts', companyId] });
      notifications.show({ color: 'green', message: 'Added' });
      setName(''); setCode(''); setLast4('');
    },
  });
  return (
    <Paper withBorder radius="md" p="md">
      <Text fw={700} mb="sm">Add</Text>
      <Stack>
        <SegmentedControl value={kind} onChange={setKind}
          data={[{ value: 'bank', label: 'Bank' }, { value: 'cash', label: 'Cash' }, { value: 'expense', label: 'Expense' }, { value: 'income', label: 'Income' }]} />
        <TextInput label="Name" placeholder={kind === 'bank' ? 'Bank of Baroda current a/c' : kind === 'expense' ? 'Vehicle repairs' : ''}
          value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Group grow>
          <TextInput label="Short code" placeholder={kind === 'bank' ? 'BOB-1' : 'EXP-REP'} value={code}
            onChange={(e) => setCode(e.currentTarget.value.toUpperCase())} />
          {kind === 'bank' && <TextInput label="Last 4 digits" inputMode="numeric" maxLength={4} value={last4}
            onChange={(e) => setLast4(e.currentTarget.value.replace(/\D/g, ''))} />}
        </Group>
        {m.error && <Alert color="red">{(m.error as ApiError).message}</Alert>}
        <Button disabled={!name.trim() || !/^[A-Z0-9-]{2,20}$/.test(code)} loading={m.isPending} onClick={() => m.mutate()}>Add</Button>
      </Stack>
    </Paper>
  );
}
