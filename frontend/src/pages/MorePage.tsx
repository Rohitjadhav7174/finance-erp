import { Badge, NavLink, Paper, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { useCompany } from '../context/CompanyContext';
import { IconBuilding, IconChart, IconClock, IconList, IconLogout, IconReceipt, IconSearch, IconSwap, IconUsers } from '../layout/icons';
import { ROLE_LABELS } from '../lib/format';

export function MorePage() {
  const { me, company, can } = useCompany();
  const { signOut } = useAuth();
  if (!me || !company) return null;
  const admin = can('company_admin');
  return (
    <Stack maw={640}>
      <Title order={3}>More</Title>
      <Paper withBorder p="md">
        <Text fw={700}>{me.profile.full_name}</Text>
        <Text size="sm" c="dimmed">{me.profile.email}</Text>
        <Badge mt="xs" variant="light">{ROLE_LABELS[company.role]} · {company.code}</Badge>
      </Paper>

      <Text fw={700} size="sm" c="dimmed">Daily work</Text>
      <Paper withBorder>
        <NavLink component={Link} to="/pending" label="Pending work" description="Overdue installments, drafts, approvals" leftSection={<IconClock />} />
        <NavLink component={Link} to="/search" label="Search" leftSection={<IconSearch />} />
        {admin && <NavLink component={Link} to="/approvals" label="Approvals" description="Reversal requests" leftSection={<IconClock />} />}
      </Paper>

      <Text fw={700} size="sm" c="dimmed">Details &amp; other entry types</Text>
      <Paper withBorder>
        <NavLink component={Link} to="/entries" label="All entries (list)" leftSection={<IconList />} />
        <NavLink component={Link} to="/bills" label="Bills & installments" leftSection={<IconReceipt />} />
        {can('data_entry') && <NavLink component={Link} to="/new/payment" label="Pay a supplier" leftSection={<IconSwap />} />}
        {can('data_entry') && <NavLink component={Link} to="/new/transfer" label="Cash ↔ bank transfer" leftSection={<IconSwap />} />}
        {can('accountant') && <NavLink component={Link} to="/reconcile" label="Reconcile cash & bank" leftSection={<IconSwap />} />}
      </Paper>

      <Text fw={700} size="sm" c="dimmed">Setup</Text>
      <Paper withBorder>
        <NavLink component={Link} to="/accounts" label="Accounts & categories" description="Cash, bank, expense types" leftSection={<IconSwap />} />
        {can('accountant') && <NavLink component={Link} to="/imports" label="Import from Excel" leftSection={<IconChart />} />}
        {admin && (
          <>
            <NavLink component={Link} to="/opening-balances" label="Opening balances" leftSection={<IconSwap />} />
            <NavLink component={Link} to="/users" label="Employees" leftSection={<IconUsers />} />
            <NavLink component={Link} to="/companies" label="Companies & sites" leftSection={<IconBuilding />} />
            {me.profile.is_super_admin && <NavLink component={Link} to="/backups" label="Backups" leftSection={<IconBuilding />} />}
          </>
        )}
        <NavLink label="Sign out" leftSection={<IconLogout />} onClick={signOut} c="red" />
      </Paper>
    </Stack>
  );
}
