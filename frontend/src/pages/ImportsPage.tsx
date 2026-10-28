import { Alert, Anchor, Badge, Box, Button, Checkbox, Collapse, FileButton, Group, Loader, Modal, Paper, Select, SimpleGrid, Stack, Table, Text, TextInput, Title, UnstyledButton } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { EmptyState } from '../components/CompanyPicker';
import { DateField, PartySelect, StatusBadge } from '../components/fields';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, download, json } from '../lib/api';
import { formatDate, formatINR } from '../lib/format';
import { accountLabel, byType, moneyAccounts, useAccounts } from '../lib/hooks';

interface Issue { level: 'error' | 'warning' | 'info'; code: string; message: string }
interface Row {
  id: string; sheet: string; row_number: number; part: number; decision: string; blocking: boolean;
  raw: Record<string, { v: unknown; fmt?: string; comment?: string }>;
  effective: Record<string, string | null> | null; overrides: Record<string, string>; all_issues: Issue[];
  entries: { id: string; entry_no: string | null; status: string }[] | null;
}
interface Batch {
  id: string; company_id: string; file_name: string; file_sha256: string; status: string; version: number;
  created_at: string; uploaded_by_name: string; confirmed_by_name: string | null; profile: string;
  sheets: { sheet: string; title: string; profile: string | null; data_rows: number; message: string | null }[];
  defaults: { receipt: Record<string, string | null>; expense: Record<string, string | null>; site_id?: string | null };
  rows: Row[]; totals: Record<string, string>;
  counts: { data_rows: number; to_import: number; skipped: number; blocking: number; warnings: number; info_rows: number };
  reconciliation: { sheet: string; cell: string; formula: string; excel_value: string | null; recomputed: string | null; importing: string; status: string; note: string | null }[];
  ledger: { posted: string; drafts: string; posted_count: number; draft_count: number };
  confirmation_phrase: string;
}

const LEVEL_COLOR = { error: 'red', warning: 'orange', info: 'gray' } as const;

export function ImportsPage() {
  const { company, can } = useCompany();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ['imports', company?.id],
    queryFn: () => api<{ id: string; file_name: string; status: string; created_at: string; uploaded_by_name: string; data_rows: number }[]>(`/companies/${company!.id}/imports`),
    enabled: !!company,
  });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append('file', file);
      return api<Batch>(`/companies/${company!.id}/imports`, { method: 'POST', body: fd });
    },
    onSuccess: (b) => { qc.invalidateQueries({ queryKey: ['imports'] }); navigate(`/imports/${b.id}`); },
  });
  if (!can('accountant')) return <Alert color="orange">Only accountants and admins can import files.</Alert>;
  return (
    <Stack maw={820}>
      <Title order={3}>Import from Excel</Title>
      <Paper withBorder radius="md" p="md">
        <Stack gap="xs">
          <Text size="sm">Nothing is saved to the books until you review a preview and a company admin confirms. Confirmed rows become <b>drafts</b> that an accountant checks and posts.</Text>
          <Text size="sm" c="dimmed">Accepted: .xlsx up to 5 MB. Recognised layouts: the monthly balance sheet used so far, and the one-row-per-transaction template.</Text>
          {upload.error && <Alert color="red">{(upload.error as ApiError).message}</Alert>}
          <Group>
            <FileButton accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(f) => f && upload.mutate(f)}>
              {(props) => <Button {...props} loading={upload.isPending}>Choose Excel file</Button>}
            </FileButton>
            <Anchor component="button" size="sm" onClick={() => download('/imports-template', 'transaction_import_template.xlsx')
              .catch((e) => notifications.show({ color: 'red', message: e.message }))}>Download template</Anchor>
          </Group>
        </Stack>
      </Paper>
      <Text fw={700}>Previous imports</Text>
      {list.isLoading && <Loader />}
      {list.data?.length === 0 && <EmptyState title="No imports yet" />}
      {list.data?.map((b) => (
        <UnstyledButton key={b.id} component={Link} to={`/imports/${b.id}`}>
          <Paper withBorder radius="md" p="sm">
            <Group justify="space-between" wrap="nowrap">
              <Box style={{ minWidth: 0 }}>
                <Text fw={600} truncate>{b.file_name}</Text>
                <Text size="xs" c="dimmed">{new Date(b.created_at).toLocaleString('en-IN')} · {b.uploaded_by_name} · {b.data_rows} rows</Text>
              </Box>
              <Badge variant="light" color={b.status === 'posted' ? 'green' : b.status === 'discarded' ? 'gray' : b.status === 'confirmed' ? 'blue' : 'yellow'}>{b.status}</Badge>
            </Group>
          </Paper>
        </UnstyledButton>
      ))}
    </Stack>
  );
}

export function ImportDetailPage() {
  const { id } = useParams();
  const { can } = useCompany();
  const qc = useQueryClient();
  const accounts = useAccounts();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const key = ['import', id];
  const { data: b, isLoading, error } = useQuery({ queryKey: key, queryFn: () => api<Batch>(`/imports/${id}`) });
  const set = (data: Batch) => qc.setQueryData(key, data);
  const onError = (e: Error) => notifications.show({ color: 'red', title: 'Not saved', message: e.message });
  const saveDefaults = useMutation({
    mutationFn: (d: Batch['defaults']) => api<Batch>(`/imports/${id}`, { method: 'PATCH', body: json({ ...d, version: b!.version }) }),
    onSuccess: set, onError,
  });
  const patchRow = useMutation({
    mutationFn: (v: { row: string; body: object }) => api<Batch>(`/imports/${id}/rows/${v.row}`, { method: 'PATCH', body: json(v.body) }),
    onSuccess: set, onError,
  });
  const postDrafts = useMutation({
    mutationFn: () => api<Batch & { posted: number; failed: { row: number; reason: string }[] }>(`/imports/${id}/post-drafts`, { method: 'POST' }),
    onSuccess: (r) => {
      set(r);
      qc.invalidateQueries({ queryKey: ['entries'] });
      notifications.show({ color: r.failed.length ? 'orange' : 'green', message: `Posted ${r.posted}${r.failed.length ? `; ${r.failed.length} need attention` : ''}` });
    },
    onError,
  });
  const discard = useMutation({
    mutationFn: () => api(`/imports/${id}/discard`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }), onError,
  });

  if (isLoading) return <Loader />;
  if (error || !b) return <Alert color="red">{(error as Error)?.message ?? 'Not found'}</Alert>;
  const editable = b.status === 'previewed';
  const money = moneyAccounts(accounts.data);
  const dataRows = b.rows.filter((r) => r.effective);
  const shown = onlyProblems ? dataRows.filter((r) => r.all_issues.some((i) => i.level !== 'info')) : dataRows;

  return (
    <Stack maw={980}>
      <Anchor component={Link} to="/imports" size="sm">← Imports</Anchor>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={3}>{b.file_name}</Title>
          <Text size="xs" c="dimmed">Uploaded {new Date(b.created_at).toLocaleString('en-IN')} by {b.uploaded_by_name} · file fingerprint {b.file_sha256.slice(0, 12)}…</Text>
        </div>
        <Badge size="lg" variant="light">{b.status}</Badge>
      </Group>

      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
        <Paper withBorder p="xs" radius="md"><Text size="xs" c="dimmed">Transactions found</Text><Text fw={700}>{b.counts.data_rows}</Text></Paper>
        <Paper withBorder p="xs" radius="md"><Text size="xs" c="dimmed">Selected to import</Text><Text fw={700}>{b.counts.to_import}</Text></Paper>
        <Paper withBorder p="xs" radius="md"><Text size="xs" c="dimmed">Need your input</Text><Text fw={700} c={b.counts.blocking ? 'red' : undefined}>{b.counts.blocking}</Text></Paper>
        <Paper withBorder p="xs" radius="md"><Text size="xs" c="dimmed">Skipped / duplicates</Text><Text fw={700}>{b.counts.skipped}</Text></Paper>
      </SimpleGrid>
      <Text size="sm">To import: received {formatINR(b.totals.receipt ?? '0')} · expenses {formatINR(b.totals.expense ?? '0')}{b.totals.bill ? ` · bills ${formatINR(b.totals.bill)}` : ''}</Text>
      {b.sheets.filter((s) => s.message).map((s) => <Alert key={s.sheet} color="gray" p="xs">Sheet “{s.sheet.trim()}”: {s.message}</Alert>)}

      {editable && (
        <Paper withBorder radius="md" p="md">
          <Text fw={700}>Information missing from the workbook</Text>
          <Text size="xs" c="dimmed" mb="sm">The workbook doesn’t say who paid or whether it was cash or bank. Choose here; you can still change single rows below. Nothing is guessed.</Text>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <PartySelect kind="customer" label="Money received was from" value={b.defaults.receipt?.party_id ?? null}
              onChange={(v) => saveDefaults.mutate({ ...b.defaults, receipt: { ...b.defaults.receipt, party_id: v } })} />
            <Select label="Money received went into" size="md" clearable value={b.defaults.receipt?.money_account_id ?? null}
              data={money.map((a) => ({ value: a.id, label: accountLabel(a) }))}
              onChange={(v) => saveDefaults.mutate({ ...b.defaults, receipt: { ...b.defaults.receipt, money_account_id: v } })} />
            <Select label="Expenses were paid from" size="md" clearable value={b.defaults.expense?.money_account_id ?? null}
              data={money.map((a) => ({ value: a.id, label: accountLabel(a) }))}
              onChange={(v) => saveDefaults.mutate({ ...b.defaults, expense: { ...b.defaults.expense, money_account_id: v } })} />
          </SimpleGrid>
        </Paper>
      )}

      <Paper withBorder radius="md" p="md">
        <Text fw={700} mb="xs">Check against the workbook’s own totals</Text>
        <Table.ScrollContainer minWidth={520}>
          <Table fz="xs">
            <Table.Thead><Table.Tr><Table.Th>Cell</Table.Th><Table.Th>Formula</Table.Th><Table.Th ta="right">Excel shows</Table.Th><Table.Th ta="right">Cells add up to</Table.Th><Table.Th ta="right">Being imported</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {b.reconciliation.map((c) => (
                <Table.Tr key={c.sheet + c.cell}>
                  <Table.Td>{c.sheet.trim()}!{c.cell}</Table.Td><Table.Td><code>{c.formula}</code>{c.note && <Text size="xs" c="orange">{c.note}</Text>}</Table.Td>
                  <Table.Td ta="right">{c.excel_value === null ? '—' : formatINR(c.excel_value, { symbol: false })}</Table.Td>
                  <Table.Td ta="right">{c.recomputed === null ? '—' : formatINR(c.recomputed, { symbol: false })}</Table.Td>
                  <Table.Td ta="right">{formatINR(c.importing, { symbol: false })}</Table.Td>
                  <Table.Td><Badge size="xs" color={c.status === 'match' ? 'green' : 'orange'} variant="light">{c.status === 'match' ? 'matches' : 'differs'}</Badge></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {b.status !== 'previewed' && (
          <Text size="sm" mt="xs">In the books: {formatINR(b.ledger.posted)} posted ({b.ledger.posted_count}) · {formatINR(b.ledger.drafts)} in drafts ({b.ledger.draft_count})</Text>
        )}
      </Paper>

      <Group justify="space-between">
        <Text fw={700}>Rows</Text>
        <Checkbox label="Only rows with problems" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.currentTarget.checked)} />
      </Group>
      <Stack gap="xs">
        {shown.map((r) => <ImportRow key={r.id} r={r} editable={editable} accounts={accounts.data ?? []}
          onPatch={(body) => patchRow.mutate({ row: r.id, body })} />)}
      </Stack>

      {editable ? (
        <Group grow>
          <Button variant="default" color="red" onClick={() => discard.mutate()} loading={discard.isPending}>Discard import</Button>
          <Button disabled={!can('company_admin') || b.counts.blocking > 0 || b.counts.to_import === 0} onClick={() => setConfirmOpen(true)}>
            {can('company_admin') ? `Confirm ${b.counts.to_import} rows` : 'A company admin must confirm'}
          </Button>
        </Group>
      ) : b.status === 'confirmed' && can('accountant') ? (
        <Button onClick={() => postDrafts.mutate()} loading={postDrafts.isPending}>Check done — post {b.ledger.draft_count} drafts</Button>
      ) : null}
      {editable && b.counts.blocking > 0 && <Text size="xs" c="red">Fix or skip the {b.counts.blocking} rows marked “needs input” before confirming.</Text>}
      <ConfirmModal b={b} opened={confirmOpen} onClose={() => setConfirmOpen(false)} onDone={(nb) => { setConfirmOpen(false); set(nb); qc.invalidateQueries({ queryKey: ['entries'] }); }} />
    </Stack>
  );
}

function ImportRow({ r, editable, accounts, onPatch }: {
  r: Row; editable: boolean; accounts: import('../lib/hooks').Account[]; onPatch: (b: object) => void;
}) {
  const [open, setOpen] = useState(false);
  const e = r.effective!;
  const problems = r.all_issues.filter((i) => i.level !== 'info');
  const overrides = r.overrides;
  return (
    <Paper withBorder radius="md" p="sm" style={{ borderLeft: `4px solid var(--mantine-color-${r.blocking ? 'red' : problems.length ? 'orange' : 'green'}-6)`, opacity: r.decision === 'import' ? 1 : 0.6 }}>
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Box style={{ minWidth: 0 }}>
          <Text size="sm" fw={600}>{e.kind === 'receipt' ? 'Received' : e.kind === 'expense' ? `Expense · ${e.category_text ?? ''}` : 'Bill'} · {formatDate(e.entry_date)}</Text>
          <Text size="xs" c="dimmed">{r.sheet.trim()} row {r.row_number} · cell {e.source_cell}{r.entries?.length ? ` · ${r.entries[0].entry_no ?? 'draft'}` : ''}</Text>
        </Box>
        <Stack gap={2} align="flex-end">
          <Text fw={700}>{e.amount ? formatINR(e.amount) : '—'}</Text>
          {r.blocking ? <Badge size="xs" color="red">needs input</Badge> : r.decision !== 'import' ? <Badge size="xs" color="gray">{r.decision === 'duplicate' ? 'skipped: duplicate?' : 'skipped'}</Badge> : r.entries?.length ? <StatusBadge status={r.entries[0].status} /> : null}
        </Stack>
      </Group>
      {problems.map((i, k) => <Text key={k} size="xs" c={LEVEL_COLOR[i.level]}>• {i.message}</Text>)}
      <Anchor component="button" size="xs" onClick={() => setOpen((o) => !o)}>{open ? 'Hide' : 'Details & original cells'}</Anchor>
      <Collapse in={open}>
        <Stack gap="xs" mt="xs">
          <Text size="xs" c="dimmed">Original cells (kept unchanged): {Object.entries(r.raw).map(([cell, v]) => `${cell} = ${String(v.v)}`).join(' · ')}</Text>
          {r.all_issues.filter((i) => i.level === 'info').map((i, k) => <Text key={k} size="xs" c="dimmed">ℹ {i.message}</Text>)}
          {editable && (
            <SimpleGrid cols={{ base: 1, sm: 3 }}>
              <Select size="xs" label="Decision" value={r.decision} allowDeselect={false}
                data={[{ value: 'import', label: 'Import' }, { value: 'skip', label: 'Skip' }, { value: 'duplicate', label: 'Skip (duplicate)' }]}
                onChange={(v) => v && onPatch({ decision: v })} />
              <DateField size="xs" label="Correct date (if wrong)" defaultValue={overrides?.entry_date ?? ''}
                onChange={(ev) => /^\d{4}-\d{2}-\d{2}$/.test(ev.currentTarget.value)
                  && onPatch({ overrides: { ...overrides, entry_date: ev.currentTarget.value } })} />
              {e.kind === 'expense' && (
                <Select size="xs" label="Expense category" value={e.expense_account_id} allowDeselect={false}
                  data={byType(accounts, 'expense').map((a) => ({ value: a.id, label: a.name }))}
                  onChange={(v) => v && onPatch({ overrides: { ...overrides, expense_account_id: v } })} />
              )}
              <Select size="xs" label="Cash / bank for this row" clearable value={overrides?.money_account_id ?? null}
                placeholder="Use the default above" data={moneyAccounts(accounts).map((a) => ({ value: a.id, label: accountLabel(a) }))}
                onChange={(v) => onPatch({ overrides: { ...overrides, money_account_id: v } })} />
            </SimpleGrid>
          )}
        </Stack>
      </Collapse>
    </Paper>
  );
}

function ConfirmModal({ b, opened, onClose, onDone }: { b: Batch; opened: boolean; onClose: () => void; onDone: (b: Batch) => void }) {
  const [text, setText] = useState('');
  const m = useMutation({
    mutationFn: () => api<Batch & { created: number }>(`/imports/${b.id}/confirm`, { method: 'POST', body: json({ confirmation: text, version: b.version }) }),
    onSuccess: (r) => { notifications.show({ color: 'green', message: `${r.created} draft entries created` }); setText(''); onDone(r); },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="Confirm import">
      <Stack>
        <Text size="sm">{b.counts.to_import} rows will become <b>draft</b> entries in the books (received {formatINR(b.totals.receipt ?? '0')}, expenses {formatINR(b.totals.expense ?? '0')}). Nothing is posted until an accountant checks and posts them.</Text>
        {m.error && <Alert color="red">{(m.error as ApiError).message}</Alert>}
        <TextInput label={`Type ${b.confirmation_phrase} to confirm`} value={text} onChange={(e) => setText(e.currentTarget.value)} autoComplete="off" />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button disabled={text.trim().toUpperCase() !== b.confirmation_phrase} loading={m.isPending} onClick={() => m.mutate()}>Confirm</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
