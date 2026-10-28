import { Alert, Anchor, Button, Center, Divider, Group, Loader, Modal, Paper, Stack, Table, Text, Textarea, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { METHOD_LABEL, StatusBadge, TYPE_LABEL } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';

interface Detail {
  id: string; company_id: string; entry_no: string | null; entry_date: string; entry_type: string; status: string;
  description: string; notes: string | null; reference_no: string | null; payment_method: string | null;
  party_name: string | null; site_name: string | null; amount: string; version: number;
  created_by_name: string | null; approved_by_name: string | null; created_at: string; posted_at: string | null;
  reverses_entry_id: string | null; reversed_by_id: string | null; reversed_by_no: string | null; source: string;
  lines: { line_no: number; code: string; account_name: string; party_name: string | null; debit: string; credit: string }[];
  allocations: { bill_id: string; bill_no: string; amount: string }[];
  bill: { id: string; bill_no: string } | null;
  approvals: { id: string; action: string; status: string; reason: string; requested_by_name: string;
    decided_by_name: string | null; decision_note: string | null; requested_at: string }[];
  history: { at: string; action: string; actor_name: string | null; old_status: string | null; new_status: string | null }[];
  form: unknown;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Group justify="space-between" wrap="nowrap" gap="md">
      <Text size="sm" c="dimmed">{label}</Text>
      <Text size="sm" ta="right" style={{ wordBreak: 'break-word' }}>{children}</Text>
    </Group>
  );
}

export function EntryDetailPage() {
  const { id } = useParams();
  const { can } = useCompany();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [reverseOpen, setReverseOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const { data: e, isLoading, error } = useQuery({ queryKey: ['entry', id], queryFn: () => api<Detail>(`/entries/${id}`) });

  const refresh = (d?: Detail) => {
    if (d) qc.setQueryData(['entry', id], d);
    qc.invalidateQueries({ queryKey: ['entries'] });
    qc.invalidateQueries({ queryKey: ['bills'] });
    qc.invalidateQueries({ queryKey: ['approvals'] });
  };
  const onError = (err: Error) => notifications.show({ color: 'red', title: 'Not done', message: err.message });
  const act = useMutation({
    mutationFn: (path: string) => api<Detail>(`/entries/${id}/${path}`, { method: 'POST', body: json({ version: e!.version }) }),
    onSuccess: (d) => { refresh(d); notifications.show({ color: 'green', message: d.status === 'posted' ? `Posted ${d.entry_no}` : 'Updated' }); },
    onError,
  });
  const doReverse = useMutation({
    mutationFn: () => api<Detail>(`/entries/${id}/reverse`, { method: 'POST', idempotencyKey: `rev-${id}`.replace(/-/g, '') }),
    onSuccess: (d) => { refresh(); notifications.show({ color: 'green', message: `Reversed by ${d.entry_no}` }); navigate(`/entries/${d.id}`); },
    onError,
  });
  const del = useMutation({
    mutationFn: () => api(`/entries/${id}?version=${e!.version}`, { method: 'DELETE' }),
    onSuccess: () => { refresh(); notifications.show({ color: 'green', message: 'Draft deleted' }); navigate('/entries'); },
    onError,
  });

  if (isLoading) return <Center h={200}><Loader /></Center>;
  if (error || !e) return <Alert color="red">{(error as Error)?.message ?? 'Not found'}</Alert>;

  const editable = e.status === 'draft' || e.status === 'pending_approval';
  const openReq = e.approvals.find((a) => a.action === 'reverse_entry' && ['pending', 'approved'].includes(a.status));

  return (
    <Stack maw={720}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div>
          <Text size="sm" c="dimmed">{TYPE_LABEL[e.entry_type]}</Text>
          <Title order={3}>{formatINR(e.amount)}</Title>
          <Text size="sm">{e.party_name ?? e.description}</Text>
        </div>
        <StatusBadge status={e.status} />
      </Group>

      {e.status === 'reversed' && e.reversed_by_id && (
        <Alert color="red">This entry was cancelled by <Anchor component={Link} to={`/entries/${e.reversed_by_id}`}>{e.reversed_by_no}</Anchor>.</Alert>
      )}
      {e.reverses_entry_id && (
        <Alert color="gray">This reversal cancels <Anchor component={Link} to={`/entries/${e.reverses_entry_id}`}>the original entry</Anchor>.</Alert>
      )}
      {e.status === 'pending_approval' && <Alert color="yellow">Waiting for an accountant to check and post.</Alert>}

      <Paper withBorder p="md">
        <Stack gap={6}>
          <Row label="Entry no.">{e.entry_no ?? 'Assigned when posted'}</Row>
          <Row label="Date">{formatDate(e.entry_date)}</Row>
          {e.payment_method && <Row label="Method">{METHOD_LABEL[e.payment_method]}</Row>}
          {e.reference_no && <Row label="Reference">{e.reference_no}</Row>}
          <Row label="Description">{e.description}</Row>
          {e.site_name && <Row label="Site">{e.site_name}</Row>}
          {e.notes && <Row label="Notes">{e.notes}</Row>}
          {e.bill && <Row label="Bill"><Anchor component={Link} to={`/bills/${e.bill.id}`}>{e.bill.bill_no}</Anchor></Row>}
          <Row label="Entered by">{e.created_by_name ?? '—'}</Row>
          {e.approved_by_name && <Row label="Posted by">{e.approved_by_name}</Row>}
          {e.source === 'import' && <Row label="Source">Excel import</Row>}
        </Stack>
      </Paper>

      {e.allocations.length > 0 && (
        <Paper withBorder p="md">
          <Text fw={600} mb="xs">Applied to bills</Text>
          {e.allocations.map((a) => (
            <Group key={a.bill_id} justify="space-between">
              <Anchor component={Link} to={`/bills/${a.bill_id}`} size="sm">{a.bill_no}</Anchor>
              <Text size="sm">{formatINR(a.amount)}</Text>
            </Group>
          ))}
        </Paper>
      )}

      <Paper withBorder p="md">
        <Text fw={600} mb="xs">Accounting</Text>
        <Table.ScrollContainer minWidth={320}>
          <Table fz="sm" verticalSpacing={4}>
            <Table.Thead><Table.Tr><Table.Th>Account</Table.Th><Table.Th ta="right">Debit</Table.Th><Table.Th ta="right">Credit</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {e.lines.map((l) => (
                <Table.Tr key={l.line_no}>
                  <Table.Td>{l.account_name}{l.party_name ? <Text span c="dimmed" size="xs"> · {l.party_name}</Text> : null}</Table.Td>
                  <Table.Td ta="right">{l.debit !== '0.00' ? formatINR(l.debit, { symbol: false }) : ''}</Table.Td>
                  <Table.Td ta="right">{l.credit !== '0.00' ? formatINR(l.credit, { symbol: false }) : ''}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>

      {e.approvals.length > 0 && (
        <Paper withBorder p="md">
          <Text fw={600} mb="xs">Approval requests</Text>
          {e.approvals.map((a) => (
            <Stack key={a.id} gap={2} mb="xs">
              <Group justify="space-between"><Text size="sm">Reversal requested by {a.requested_by_name}</Text><StatusBadge status={a.status} /></Group>
              <Text size="xs" c="dimmed">Reason: {a.reason}</Text>
              {a.decided_by_name && <Text size="xs" c="dimmed">Decided by {a.decided_by_name}{a.decision_note ? `: ${a.decision_note}` : ''}</Text>}
            </Stack>
          ))}
        </Paper>
      )}

      {e.history.length > 0 && (
        <Paper withBorder p="md">
          <Text fw={600} mb="xs">History</Text>
          {e.history.map((h, i) => (
            <Text key={i} size="xs" c="dimmed">
              {new Date(h.at).toLocaleString('en-IN')} · {h.actor_name ?? 'system'} · {h.action === 'insert' ? 'created' : h.old_status !== h.new_status ? `${h.old_status} → ${h.new_status}` : 'edited'}
            </Text>
          ))}
        </Paper>
      )}

      <Divider />
      <Stack gap="xs">
        {editable && (
          <>
            {can('accountant') && (
              <Button size="md" loading={act.isPending && act.variables === 'post'} onClick={() => act.mutate('post')}>Check &amp; post</Button>
            )}
            {e.status === 'draft' && !can('accountant') && (
              <Button size="md" loading={act.isPending} onClick={() => act.mutate('submit')}>Send for approval</Button>
            )}
            {e.status === 'pending_approval' && (
              <Button size="md" variant="default" onClick={() => act.mutate('return-to-draft')}>Return to draft</Button>
            )}
            <Button size="md" variant="default" component={Link} to={`/entries/${e.id}/edit`}>Edit</Button>
            <Button size="md" variant="subtle" color="red" onClick={() => setDeleteOpen(true)}>Delete draft</Button>
          </>
        )}
        {e.status === 'posted' && e.entry_type !== 'reversal' && can('accountant') && (
          openReq?.status === 'approved' ? (
            <Button size="md" color="red" loading={doReverse.isPending} onClick={() => doReverse.mutate()}>Reverse now (approved)</Button>
          ) : openReq ? (
            <Text size="sm" c="dimmed" ta="center">Reversal requested — waiting for a company admin.</Text>
          ) : (
            <Button size="md" variant="subtle" color="red" onClick={() => setReverseOpen(true)}>Request reversal</Button>
          )
        )}
      </Stack>

      <ReverseModal opened={reverseOpen} id={e.id} onClose={() => setReverseOpen(false)} onDone={(d) => { setReverseOpen(false); refresh(d); }} />
      <Modal opened={deleteOpen} onClose={() => setDeleteOpen(false)} title="Delete this draft?">
        <Stack>
          <Text size="sm">The draft will be removed. This is recorded in the audit log.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleteOpen(false)}>Keep</Button>
            <Button color="red" loading={del.isPending} onClick={() => del.mutate()}>Delete</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

function ReverseModal({ opened, id, onClose, onDone }: { opened: boolean; id: string; onClose: () => void; onDone: (d: Detail) => void }) {
  const [reason, setReason] = useState('');
  const m = useMutation({
    mutationFn: () => api<Detail>(`/entries/${id}/reversal-request`, { method: 'POST', body: json({ reason }) }),
    onSuccess: (d) => { setReason(''); notifications.show({ color: 'green', message: 'Reversal requested' }); onDone(d); },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="Request a reversal">
      <Stack>
        <Text size="sm">Posted entries are never deleted. A company admin must approve, then a mirror entry cancels this one. Both stay in the records.</Text>
        {m.error && <Alert color="red">{(m.error as ApiError).message}</Alert>}
        <Textarea label="Why should it be reversed?" minRows={2} value={reason} onChange={(ev) => setReason(ev.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color="red" disabled={reason.trim().length < 5} loading={m.isPending} onClick={() => m.mutate()}>Request</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
