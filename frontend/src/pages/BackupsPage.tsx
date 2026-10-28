import { Alert, Anchor, Badge, Group, Loader, Paper, Stack, Table, Text, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { useCompany } from '../context/CompanyContext';
import { api } from '../lib/api';

export interface BackupHealth {
  last_success_at: string | null; last_verified_at: string | null; last_status: string | null;
  last_error_at: string | null; max_age_hours: number; overdue: boolean;
}

const when = (s: string | null) => (s ? new Date(s).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : 'never');

/** Warning shown to administrators on every page when backups failed or are overdue. */
export function BackupBanner() {
  const { can } = useCompany();
  const { data } = useQuery({
    queryKey: ['backup-health'],
    queryFn: () => api<BackupHealth>('/admin/backup-health'),
    enabled: can('company_admin'),
    staleTime: 10 * 60_000,
    retry: false,
  });
  if (!data || (!data.overdue && data.last_status !== 'failed')) return null;
  return (
    <Alert color="red" title={data.last_status === 'failed' ? 'The last backup FAILED' : 'Backups are overdue'} mb="md">
      Last successful backup: {when(data.last_success_at)}. Financial records are at risk until a backup succeeds.{' '}
      <Anchor component={Link} to="/backups">Details</Anchor>
    </Alert>
  );
}

interface Run {
  id: string; started_at: string; finished_at: string | null; status: string; object_key: string | null;
  size_bytes: number | null; sha256: string | null; verified_at: string | null; error: string | null;
  row_counts: Record<string, number> | null;
}

const COLOR: Record<string, string> = { verified: 'green', succeeded: 'teal', running: 'blue', failed: 'red' };

export function BackupsPage() {
  const { me } = useCompany();
  const { data, isLoading, error } = useQuery({
    queryKey: ['backups'],
    queryFn: () => api<{ health: BackupHealth; runs: Run[] }>('/admin/backups'),
    enabled: !!me?.profile.is_super_admin,
  });
  if (!me?.profile.is_super_admin) return <Alert color="orange">Only the super admin can see backup details.</Alert>;
  if (isLoading) return <Loader />;
  if (error || !data) return <Alert color="red">{(error as Error)?.message}</Alert>;
  const h = data.health;
  return (
    <Stack maw={900}>
      <Title order={3}>Backups</Title>
      <Paper withBorder radius="md" p="md">
        <Group justify="space-between">
          <Stack gap={2}>
            <Text size="sm">Last successful backup: <b>{when(h.last_success_at)}</b></Text>
            <Text size="sm">Last restore test passed: <b>{when(h.last_verified_at)}</b></Text>
            <Text size="xs" c="dimmed">A warning appears if no backup succeeds within {h.max_age_hours} hours.</Text>
          </Stack>
          <Badge size="lg" color={h.overdue || h.last_status === 'failed' ? 'red' : 'green'}>{h.overdue ? 'Overdue' : h.last_status === 'failed' ? 'Failed' : 'Healthy'}</Badge>
        </Group>
      </Paper>
      <Text size="sm" c="dimmed">
        Backups run every night outside this app, are encrypted before leaving the server, and are stored off-site.
        A weekly job restores the newest backup into a separate database and checks every count and total.
        Restoring into the live system is a manual, documented procedure (docs/05) — it is deliberately not a button.
      </Text>
      <Paper withBorder radius="md">
        <Table.ScrollContainer minWidth={640}>
          <Table fz="xs" striped>
            <Table.Thead><Table.Tr><Table.Th>Started</Table.Th><Table.Th>Status</Table.Th><Table.Th>File</Table.Th><Table.Th ta="right">Size</Table.Th><Table.Th ta="right">Entries</Table.Th><Table.Th>Restore-tested</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {data.runs.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td>{when(r.started_at)}</Table.Td>
                  <Table.Td><Badge size="xs" color={COLOR[r.status]}>{r.status}</Badge>{r.error && <Text size="xs" c="red">{r.error}</Text>}</Table.Td>
                  <Table.Td><code>{r.object_key ?? '—'}</code></Table.Td>
                  <Table.Td ta="right">{r.size_bytes ? `${(r.size_bytes / 1024).toFixed(0)} KB` : '—'}</Table.Td>
                  <Table.Td ta="right">{r.row_counts?.journal_entries ?? '—'}</Table.Td>
                  <Table.Td>{r.verified_at ? when(r.verified_at) : '—'}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {data.runs.length === 0 && <Text p="md" size="sm" c="red">No backup has ever run. Set up the nightly job before entering real data (docs/05).</Text>}
      </Paper>
    </Stack>
  );
}
