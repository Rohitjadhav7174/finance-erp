import { Alert, Badge, Box, Button, Group, Loader, Modal, Paper, SimpleGrid, Stack, Switch, Text, Textarea } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';
import { sumAmounts, toPaise } from '../lib/money';
import { periodLabel } from '../lib/period';
import { EmptyState } from './CompanyPicker';

export interface SavedRow {
  key: string; entry_date: string; period_from: string | null; period_to: string | null; bill_no: string | null;
  monthly_bill: string | null; installment_received: string | null; other_expense: string | null;
  payments: { account_id: string; label: string; amount: string }[];
  installments: { received_on: string; amount: string; receipt_no: string | null }[];
  entry_nos: string[]; status: 'posted' | 'draft' | 'pending_approval' | 'cancel_requested' | 'cancelled';
}

const STATUS: Record<SavedRow['status'], { label: string; color: string }> = {
  posted: { label: 'Saved', color: 'green' },
  draft: { label: 'Draft', color: 'gray' },
  pending_approval: { label: 'Waiting approval', color: 'yellow' },
  cancel_requested: { label: 'Delete requested', color: 'orange' },
  cancelled: { label: 'Deleted', color: 'gray' },
};

/** Period of a saved row: its bill's period, else the month of its date. */
export const rowPeriod = (r: SavedRow) => {
  const from = r.period_from ?? `${r.entry_date.slice(0, 7)}-01`;
  return { from, to: r.period_to ?? from };
};

function Figure({ label, value }: { label: string; value: string | null }) {
  return (
    <Box>
      <Text size="xs" c="dimmed" fw={600}>{label}</Text>
      <Text fw={700} className="amount">{value ? formatINR(value) : '—'}</Text>
    </Box>
  );
}

/** Every saved monthly form as one row, like the Excel sheet, with Edit and Delete. */
export function SavedMonthlyEntries({ onEdit }: { onEdit: (row: SavedRow) => void }) {
  const { company, me, can } = useCompany();
  const [showDeleted, setShowDeleted] = useState(false);
  const [deleting, setDeleting] = useState<SavedRow | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ['monthly-entries', company?.id],
    queryFn: () => api<SavedRow[]>(`/companies/${company!.id}/monthly-entries`),
    enabled: !!company,
  });
  const owner = !!me?.profile.is_super_admin;
  const rows = (data ?? []).filter((r) => showDeleted || r.status !== 'cancelled');

  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">{rows.length} saved entr{rows.length === 1 ? 'y' : 'ies'}, newest first</Text>
        <Switch label="Show deleted" checked={showDeleted} onChange={(e) => setShowDeleted(e.currentTarget.checked)} />
      </Group>
      {isLoading && <Loader />}
      {error && <Alert color="red">{(error as Error).message}</Alert>}
      {data && rows.length === 0 && <EmptyState title="No saved entries yet">Entries you save with the form appear here.</EmptyState>}
      {rows.map((r) => {
        const p = rowPeriod(r);
        const open = r.status !== 'cancelled' && r.status !== 'cancel_requested';
        const unposted = r.status === 'draft' || r.status === 'pending_approval';
        const expenses = sumAmounts([...r.payments.map((x) => x.amount), ...(r.other_expense ? [r.other_expense] : [])]);
        return (
          <Paper key={r.key} withBorder p="md" style={r.status === 'cancelled' ? { opacity: 0.6 } : undefined}>
            <Group justify="space-between" align="flex-start" wrap="nowrap" mb="xs">
              <Box style={{ minWidth: 0 }}>
                <Text fw={700} size="lg">{periodLabel(p.from, p.to)}</Text>
                <Text size="xs" c="dimmed">Date {formatDate(r.entry_date)}{r.bill_no ? ` · Bill ${r.bill_no}` : ''}</Text>
              </Box>
              <Badge variant="light" color={STATUS[r.status].color}>{STATUS[r.status].label}</Badge>
            </Group>
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
              <Figure label="Monthly Bill" value={r.monthly_bill} />
              <Figure label="Installment Received" value={r.installment_received} />
              <Figure label="Expenses" value={toPaise(expenses) > 0n ? expenses : null} />
              <Figure label="Other Expense" value={r.other_expense} />
            </SimpleGrid>
            {r.installments.length > 1 && (
              <Text size="xs" c="dimmed" mt="xs">
                Installments: {r.installments.map((x) => `${formatDate(x.received_on)} ${formatINR(x.amount)}`).join(' · ')}
              </Text>
            )}
            {r.payments.length > 0 && (
              <Text size="xs" c="dimmed" mt="xs">
                {r.payments.map((x) => `${x.label} ${formatINR(x.amount)}`).join(' · ')}
              </Text>
            )}
            {open && can('data_entry') && (
              <Group gap="xs" mt="sm">
                {(owner || unposted) && (
                  <Button size="xs" variant="light" onClick={() => onEdit(r)} aria-label={`Edit ${periodLabel(p.from, p.to)}`}>Edit</Button>
                )}
                <Button size="xs" variant="subtle" color="red" onClick={() => setDeleting(r)}
                  aria-label={`Delete ${periodLabel(p.from, p.to)}`}>Delete</Button>
              </Group>
            )}
          </Paper>
        );
      })}
      <DeleteModal row={deleting} owner={owner} onClose={() => setDeleting(null)} />
    </Stack>
  );
}

function DeleteModal({ row, owner, onClose }: { row: SavedRow | null; owner: boolean; onClose: () => void }) {
  const { company } = useCompany();
  const qc = useQueryClient();
  const [reason, setReason] = useState('');
  const unposted = row?.status === 'draft' || row?.status === 'pending_approval';
  const now = owner || unposted;
  const m = useMutation({
    mutationFn: () => api<{ status: string }>(`/companies/${company!.id}/monthly-entries/${row!.key}/cancel`,
      { method: 'POST', body: json({ reason: reason.trim() }) }),
    onSuccess: (r) => {
      qc.invalidateQueries();
      notifications.show({ color: 'green', message: r.status === 'cancelled' ? 'Entry deleted' : 'Sent to an admin for approval' });
      setReason('');
      onClose();
    },
  });
  const p = row ? rowPeriod(row) : null;
  return (
    <Modal opened={!!row} onClose={onClose} title={`Delete ${p ? periodLabel(p.from, p.to) : ''}?`}>
      <Stack>
        <Text size="sm">
          {now
            ? 'The bill, installment and payments of this entry are removed from all totals. It stays in the history as deleted.'
            : 'This entry is already in the books, so an admin must approve the delete. Until then it still counts.'}
        </Text>
        {m.error && <Alert color="red">{(m.error as ApiError).message}</Alert>}
        <Textarea label="Reason" placeholder="e.g. Entered twice, wrong amount" value={reason} minRows={2} data-autofocus
          onChange={(e) => setReason(e.currentTarget.value)} description="At least 5 letters. Kept in the history." />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Keep it</Button>
          <Button color="red" loading={m.isPending} disabled={reason.trim().length < 5} onClick={() => m.mutate()}>
            {now ? 'Delete' : 'Ask to delete'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
