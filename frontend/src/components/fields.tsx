import { Badge, Button, Group, Modal, Select, Stack, TextInput, type SelectProps, type TextInputProps } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { useParties, type Party } from '../lib/hooks';

/** Large numeric field; keeps the value as a string (never a float). */
export function AmountInput(props: TextInputProps) {
  return (
    <TextInput inputMode="decimal" autoComplete="off" size="lg" leftSection="₹"
      styles={{ input: { fontWeight: 700, fontSize: 22 } }} {...props} />
  );
}

/** Native date picker (best on phones). */
export function DateField(props: TextInputProps) {
  return <TextInput type="date" size="md" {...props} />;
}

const KIND_LABEL: Record<string, string> = { customer: 'Customer', supplier: 'Supplier', employee: 'Employee', other: 'Other' };

export function PartySelect({ kind, value, onChange, label = 'Party', error, required }: {
  kind?: 'customer' | 'supplier'; value: string | null; onChange: (id: string | null) => void;
  label?: string; error?: React.ReactNode; required?: boolean;
}) {
  const { data } = useParties();
  const [adding, setAdding] = useState(false);
  const list = (data ?? []).filter((p) => !kind || p.kind === kind || p.kind === 'other' || p.id === value);
  return (
    <>
      <Group align="flex-end" gap="xs" wrap="nowrap">
        <Select label={label} placeholder="Search name" searchable clearable={!required} size="md" style={{ flex: 1 }}
          nothingFoundMessage="No match — add a new party" value={value} onChange={onChange} error={error}
          data={list.map((p) => ({ value: p.id, label: p.name }))} withAsterisk={required} />
        <Button variant="light" size="md" onClick={() => setAdding(true)} aria-label="Add new party">+ New</Button>
      </Group>
      <NewPartyModal opened={adding} kind={kind ?? 'customer'} onClose={() => setAdding(false)}
        onCreated={(p) => { onChange(p.id); setAdding(false); }} />
    </>
  );
}

function NewPartyModal({ opened, kind, onClose, onCreated }: {
  opened: boolean; kind: string; onClose: () => void; onCreated: (p: Party) => void;
}) {
  const { company } = useCompany();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [k, setK] = useState(kind);
  const m = useMutation({
    mutationFn: () => api<Party>(`/companies/${company!.id}/parties`, {
      method: 'POST', body: json({ name: name.trim(), kind: k, phone: phone.trim() || null }),
    }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['parties', company?.id] });
      notifications.show({ color: 'green', message: `${p.name} added` });
      setName(''); setPhone('');
      onCreated(p);
    },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="New party">
      <Stack>
        <TextInput label="Name" size="md" value={name} onChange={(e) => setName(e.currentTarget.value)} data-autofocus
          error={m.error ? (m.error as ApiError).message : undefined} />
        <Select label="Type" size="md" value={k} onChange={(v) => v && setK(v)} allowDeselect={false}
          data={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))} />
        <TextInput label="Phone (optional)" type="tel" inputMode="tel" size="md" value={phone}
          onChange={(e) => setPhone(e.currentTarget.value)} />
        <Button size="md" disabled={!name.trim()} loading={m.isPending} onClick={() => m.mutate()}>Add party</Button>
      </Stack>
    </Modal>
  );
}

export const METHOD_OPTIONS = [
  { value: 'cash', label: 'Cash' }, { value: 'upi', label: 'UPI' }, { value: 'bank_transfer', label: 'Bank transfer' },
  { value: 'cheque', label: 'Cheque' }, { value: 'other', label: 'Other' },
];
export const METHOD_LABEL = Object.fromEntries(METHOD_OPTIONS.map((m) => [m.value, m.label]));

export function AccountSelect(props: SelectProps) {
  return <Select size="md" allowDeselect={false} {...props} />;
}

const STATUS: Record<string, [string, string]> = {
  draft: ['Draft', 'gray'], pending_approval: ['Waiting approval', 'yellow'], posted: ['Posted', 'green'],
  reversed: ['Reversed', 'red'], pending: ['Unpaid', 'blue'], partially_paid: ['Part paid', 'orange'],
  overdue: ['Overdue', 'red'], paid: ['Paid', 'green'], cancelled: ['Cancelled', 'gray'], upcoming: ['Upcoming', 'blue'],
  approved: ['Approved', 'green'], rejected: ['Rejected', 'red'], used: ['Done', 'gray'],
};

export function StatusBadge({ status }: { status: string }) {
  const [label, color] = STATUS[status] ?? [status, 'gray'];
  return <Badge color={color} variant="light">{label}</Badge>;
}

export const TYPE_LABEL: Record<string, string> = {
  receipt: 'Receipt', payment: 'Supplier payment', expense: 'Expense', transfer: 'Transfer', bill_sale: 'Customer bill',
  bill_purchase: 'Supplier bill', opening: 'Opening balance', adjustment: 'Adjustment', reversal: 'Reversal',
};
