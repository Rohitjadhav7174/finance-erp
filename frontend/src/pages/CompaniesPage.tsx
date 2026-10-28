import { Alert, Button, ColorInput, Group, Paper, Stack, Text, TextInput, Title } from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCompany } from '../context/CompanyContext';
import { api, ApiError, json } from '../lib/api';

interface Site { id: string; name: string; is_active: boolean }

export function CompaniesPage() {
  const { company, me } = useCompany();
  const qc = useQueryClient();
  const sites = useQuery({
    queryKey: ['sites', company?.id],
    queryFn: () => api<Site[]>(`/companies/${company!.id}/sites`),
    enabled: !!company,
  });
  const siteForm = useForm({ initialValues: { name: '' }, validate: { name: (v) => (v.trim() ? null : 'Required') } });
  const addSite = useMutation({
    mutationFn: (name: string) => api(`/companies/${company!.id}/sites`, { method: 'POST', body: json({ name }) }),
    onSuccess: () => {
      siteForm.reset();
      qc.invalidateQueries({ queryKey: ['sites', company?.id] });
      notifications.show({ color: 'green', message: 'Site added' });
    },
  });

  if (!company) return null;
  return (
    <Stack>
      <Title order={3}>{company.name}</Title>
      <Paper withBorder radius="md" p="md">
        <Text fw={700} mb="xs">Sites / branches</Text>
        <Text size="sm" c="dimmed" mb="sm">Optional locations such as Sindhudurg or Ratnagiri. Entries can be tagged by site.</Text>
        <Stack gap={4} mb="sm">
          {sites.data?.length === 0 && <Text size="sm" c="dimmed">No sites yet.</Text>}
          {sites.data?.map((s) => <Text key={s.id}>• {s.name}</Text>)}
        </Stack>
        <form onSubmit={siteForm.onSubmit((v) => addSite.mutate(v.name.trim()))}>
          <Group align="flex-start" wrap="nowrap">
            <TextInput placeholder="Site name" aria-label="Site name" style={{ flex: 1 }} {...siteForm.getInputProps('name')} />
            <Button type="submit" loading={addSite.isPending}>Add</Button>
          </Group>
          {addSite.error && <Alert color="red" mt="xs">{(addSite.error as ApiError).message}</Alert>}
        </form>
      </Paper>
      {me?.profile.is_super_admin && <NewCompany />}
    </Stack>
  );
}

function NewCompany() {
  const qc = useQueryClient();
  const form = useForm({
    initialValues: { code: '', name: '', address: '', theme_color: '#2f9e44' },
    validate: {
      code: (v) => (/^[A-Z]{2,6}$/.test(v) ? null : '2–6 capital letters, e.g. JGT'),
      name: (v) => (v.trim().length >= 2 ? null : 'Required'),
    },
  });
  const create = useMutation({
    mutationFn: (v: typeof form.values) => api('/companies', { method: 'POST', body: json({ ...v, address: v.address || null }) }),
    onSuccess: () => {
      form.reset();
      qc.invalidateQueries({ queryKey: ['me'] });
      notifications.show({ color: 'green', message: 'Company created with a default chart of accounts' });
    },
  });
  return (
    <Paper withBorder radius="md" p="md">
      <Text fw={700} mb="sm">Add company (super admin)</Text>
      <form onSubmit={form.onSubmit((v) => create.mutate(v))} noValidate>
        <Stack>
          {create.error && <Alert color="red">{(create.error as ApiError).message}</Alert>}
          <TextInput label="Short code" placeholder="JGT" {...form.getInputProps('code')}
            onChange={(e) => form.setFieldValue('code', e.currentTarget.value.toUpperCase())} />
          <TextInput label="Company name" {...form.getInputProps('name')} />
          <TextInput label="Address" {...form.getInputProps('address')} />
          <ColorInput label="Colour (helps staff see which company they are in)" {...form.getInputProps('theme_color')} />
          <Button type="submit" loading={create.isPending}>Create company</Button>
        </Stack>
      </form>
    </Paper>
  );
}
