import { Alert, Badge, Button, Group, Modal, Paper, Select, Stack, Text, TextInput, Textarea, Title } from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { EmptyState } from '../components/CompanyPicker';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';
import { ROLE_LABELS } from '../lib/format';

interface Employee {
  user_id: string;
  full_name: string;
  email: string;
  phone: string | null;
  is_active: boolean;
  is_super_admin: boolean;
  role: string;
  membership_active: boolean;
}

const ROLE_OPTIONS = ['accountant', 'data_entry', 'viewer', 'company_admin'];

export function UsersPage() {
  const { company, me } = useCompany();
  const qc = useQueryClient();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [statusTarget, setStatusTarget] = useState<Employee | null>(null);
  const isSuper = !!me?.profile.is_super_admin;
  const key = ['users', company?.id];

  const { data, isLoading, error } = useQuery({
    queryKey: key,
    queryFn: () => api<Employee[]>(`/admin/users?company_id=${company!.id}`),
    enabled: !!company,
  });

  const onError = (e: Error) => notifications.show({ color: 'red', title: 'Not saved', message: e.message });
  const done = (message: string) => {
    notifications.show({ color: 'green', message });
    qc.invalidateQueries({ queryKey: key });
  };

  const changeRole = useMutation({
    mutationFn: (v: { user: Employee; role: string; active: boolean }) =>
      api(`/admin/users/${v.user.user_id}/memberships/${company!.id}`, {
        method: 'PUT', body: json({ role: v.role, is_active: v.active }),
      }),
    onSuccess: () => done('Access updated'),
    onError,
  });

  if (!company) return null;
  const roleOptions = ROLE_OPTIONS.filter((r) => isSuper || r !== 'company_admin')
    .map((r) => ({ value: r, label: ROLE_LABELS[r] }));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Employees</Title>
        <Button onClick={() => setInviteOpen(true)}>Invite</Button>
      </Group>
      <Text size="sm" c="dimmed">People with access to {company.name}. Each person signs in with their own account.</Text>

      {isLoading && <Text c="dimmed">Loading…</Text>}
      {error && <Alert color="red">{(error as Error).message}</Alert>}
      {data?.length === 0 && <EmptyState title="No employees yet">Invite your first employee.</EmptyState>}

      {data?.map((u) => {
        const self = u.user_id === me?.profile.user_id;
        const locked = self || (u.role === 'company_admin' && !isSuper);
        return (
          <Paper key={u.user_id} withBorder p="md" opacity={u.is_active && u.membership_active ? 1 : 0.6}>
            <Stack gap="xs">
              <Group justify="space-between" wrap="nowrap">
                <div style={{ minWidth: 0 }}>
                  <Text fw={700} truncate>{u.full_name}{self && ' (you)'}</Text>
                  <Text size="sm" c="dimmed" truncate>{u.email}</Text>
                </div>
                {!u.is_active ? <Badge color="red">Disabled</Badge>
                  : !u.membership_active ? <Badge color="orange">No access</Badge>
                  : u.is_super_admin ? <Badge color="violet">Super Admin</Badge> : null}
              </Group>
              <Group gap="xs" wrap="wrap">
                <Select aria-label={`Role of ${u.full_name}`} data={roleOptions} value={u.role} disabled={locked}
                  allowDeselect={false} w={170}
                  onChange={(role) => role && changeRole.mutate({ user: u, role, active: u.membership_active })} />
                {!locked && (
                  <Button variant="subtle" color={u.membership_active ? 'orange' : 'teal'}
                    onClick={() => changeRole.mutate({ user: u, role: u.role, active: !u.membership_active })}>
                    {u.membership_active ? 'Remove access' : 'Restore access'}
                  </Button>
                )}
                {isSuper && !self && (
                  <Button variant="subtle" color={u.is_active ? 'red' : 'teal'} onClick={() => setStatusTarget(u)}>
                    {u.is_active ? 'Disable account' : 'Enable account'}
                  </Button>
                )}
              </Group>
            </Stack>
          </Paper>
        );
      })}

      <InviteModal opened={inviteOpen} onClose={() => setInviteOpen(false)} roleOptions={roleOptions}
        companyId={company.id} onDone={() => done('Invitation sent')} />
      <StatusModal target={statusTarget} onClose={() => setStatusTarget(null)}
        onDone={(m) => { setStatusTarget(null); done(m); }} />
    </Stack>
  );
}

function InviteModal({ opened, onClose, roleOptions, companyId, onDone }: {
  opened: boolean; onClose: () => void; roleOptions: { value: string; label: string }[];
  companyId: string; onDone: () => void;
}) {
  const form = useForm({
    initialValues: { full_name: '', email: '', phone: '', role: 'data_entry' },
    validate: {
      full_name: (v) => (v.trim() ? null : 'Required'),
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : 'Enter a valid email'),
      phone: (v) => (!v || /^[0-9+\- ]{7,20}$/.test(v) ? null : 'Enter a valid phone number'),
    },
  });
  const invite = useMutation({
    mutationFn: (v: typeof form.values) =>
      api('/admin/users', { method: 'POST', body: json({ ...v, phone: v.phone || null, company_id: companyId }) }),
    onSuccess: () => { form.reset(); onClose(); onDone(); },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="Invite employee" fullScreen={window.innerWidth < 576}>
      <form onSubmit={form.onSubmit((v) => invite.mutate(v))} noValidate>
        <Stack>
          {invite.error && <Alert color="red">{(invite.error as ApiError).message}</Alert>}
          <TextInput label="Full name" size="md" {...form.getInputProps('full_name')} />
          <TextInput label="Email" type="email" inputMode="email" size="md" {...form.getInputProps('email')} />
          <TextInput label="Phone (optional)" type="tel" inputMode="tel" size="md" {...form.getInputProps('phone')} />
          <Select label="Role" data={roleOptions} allowDeselect={false} size="md" {...form.getInputProps('role')} />
          <Text size="xs" c="dimmed">They will get an email to set their own password.</Text>
          <Button type="submit" size="md" loading={invite.isPending}>Send invitation</Button>
        </Stack>
      </form>
    </Modal>
  );
}

function StatusModal({ target, onClose, onDone }: {
  target: Employee | null; onClose: () => void; onDone: (msg: string) => void;
}) {
  const [reason, setReason] = useState('');
  const disabling = !!target?.is_active;
  const m = useMutation({
    mutationFn: () => api<{ login_provider_updated: boolean }>(
      `/admin/users/${target!.user_id}/${disabling ? 'deactivate' : 'reactivate'}`,
      { method: 'POST', body: json({ reason }) }),
    onSuccess: (r) => {
      setReason('');
      onDone(r.login_provider_updated ? (disabling ? 'Account disabled' : 'Account enabled')
        : 'Data access changed, but the sign-in service did not update. Try again later.');
    },
  });
  return (
    <Modal opened={!!target} onClose={onClose} title={disabling ? 'Disable account?' : 'Enable account?'}>
      <Stack>
        <Text size="sm">
          {disabling
            ? `${target?.full_name} will immediately lose access to all companies and will not be able to sign in.`
            : `${target?.full_name} will be able to sign in again with their existing company access.`}
        </Text>
        {m.error && <Alert color="red">{(m.error as ApiError).message}</Alert>}
        <Textarea label="Reason (recorded in the audit log)" minRows={2} value={reason}
          onChange={(e) => setReason(e.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color={disabling ? 'red' : 'teal'} disabled={reason.trim().length < 5} loading={m.isPending}
            onClick={() => m.mutate()}>
            {disabling ? 'Disable' : 'Enable'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
