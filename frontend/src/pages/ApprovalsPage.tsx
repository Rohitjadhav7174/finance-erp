import { Alert, Anchor, Button, Group, Loader, Modal, Paper, SegmentedControl, Stack, Text, Textarea, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '../components/CompanyPicker';
import { StatusBadge, TYPE_LABEL } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';

interface Approval {
  id: string; action: string; status: string; reason: string; target_id: string; requested_at: string;
  requested_by_name: string; decided_by_name: string | null; decision_note: string | null; is_mine: boolean;
  entry_no: string | null; entry_date: string | null; entry_type: string | null; description: string | null; amount: string | null;
}

const ACTION_LABEL: Record<string, string> = {
  reverse_entry: 'Reverse entry', opening_balance: 'Change opening balance',
  post_in_closed_period: 'Post into closed month', reopen_period: 'Reopen month',
};

export function ApprovalsPage() {
  const { company, me } = useCompany();
  const [status, setStatus] = useState('pending');
  const [deciding, setDeciding] = useState<{ a: Approval; decision: 'approve' | 'reject' } | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ['approvals', company?.id, status],
    queryFn: () => api<Approval[]>(`/companies/${company!.id}/approvals?status=${status}`),
    enabled: !!company,
  });
  return (
    <Stack maw={720}>
      <Title order={3}>Approvals</Title>
      <SegmentedControl value={status} onChange={setStatus}
        data={[{ value: 'pending', label: 'Waiting' }, { value: 'approved', label: 'Approved' }, { value: 'all', label: 'All' }]} />
      {isLoading && <Loader />}
      {error && <Alert color="red">{(error as Error).message}</Alert>}
      {data?.length === 0 && <EmptyState title="Nothing waiting">Requests to reverse entries appear here.</EmptyState>}
      {data?.map((a) => {
        const selfBlocked = a.is_mine && !me?.profile.is_super_admin;
        return (
          <Paper key={a.id} withBorder p="md">
            <Stack gap={6}>
              <Group justify="space-between">
                <Text fw={700}>{ACTION_LABEL[a.action]}</Text>
                <StatusBadge status={a.status} />
              </Group>
              {a.entry_type && (
                <Anchor component={Link} to={`/entries/${a.target_id}`} size="sm">
                  {TYPE_LABEL[a.entry_type]} {a.entry_no} · {formatDate(a.entry_date)} · {formatINR(a.amount)}
                </Anchor>
              )}
              {a.description && <Text size="sm" c="dimmed">{a.description}</Text>}
              <Text size="sm">“{a.reason}” — {a.requested_by_name}</Text>
              {a.decided_by_name && <Text size="xs" c="dimmed">Decided by {a.decided_by_name}{a.decision_note ? `: ${a.decision_note}` : ''}</Text>}
              {a.status === 'pending' && (
                selfBlocked ? (
                  <Text size="xs" c="dimmed">You made this request, so another admin must decide it.</Text>
                ) : (
                  <Group grow>
                    <Button variant="default" onClick={() => setDeciding({ a, decision: 'reject' })}>Reject</Button>
                    <Button color="red" onClick={() => setDeciding({ a, decision: 'approve' })}>Approve</Button>
                  </Group>
                )
              )}
            </Stack>
          </Paper>
        );
      })}
      <DecideModal state={deciding} onClose={() => setDeciding(null)} />
    </Stack>
  );
}

function DecideModal({ state, onClose }: { state: { a: Approval; decision: 'approve' | 'reject' } | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const m = useMutation({
    mutationFn: () => api(`/approvals/${state!.a.id}/decide`, { method: 'POST', body: json({ decision: state!.decision, note: note.trim() || null }) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['approvals'] });
      qc.invalidateQueries({ queryKey: ['entry', state!.a.target_id] });
      notifications.show({ color: 'green', message: state!.decision === 'approve' ? 'Approved' : 'Rejected' });
      setNote('');
      onClose();
    },
  });
  const needNote = state?.a.is_mine; // super admin self-approval requires a written note
  return (
    <Modal opened={!!state} onClose={onClose} title={state?.decision === 'approve' ? 'Approve request?' : 'Reject request?'}>
      <Stack>
        {state?.decision === 'approve' && (
          <Text size="sm">After approval, the accountant can reverse the entry. The original and the reversal both stay in the records.</Text>
        )}
        {m.error && <Alert color="red">{(m.error as ApiError).message}</Alert>}
        <Textarea label={needNote ? 'Note (required for your own request)' : 'Note (optional)'} value={note}
          onChange={(e) => setNote(e.currentTarget.value)} minRows={2} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color={state?.decision === 'approve' ? 'red' : 'gray'} loading={m.isPending}
            disabled={!!needNote && note.trim().length < 5} onClick={() => m.mutate()}>
            {state?.decision === 'approve' ? 'Approve' : 'Reject'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
