import { Avatar, Badge, Box, Group, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { useAuth } from '../auth/AuthProvider';
import { MenuGroup, MenuRow } from '../components/MenuList';
import { useCompany } from '../context/CompanyContext';
import {
  IconBook, IconBuilding, IconCheck, IconClock, IconDatabase, IconList, IconLogout, IconReceipt, IconScale, IconSearch,
  IconSwap, IconUpload, IconUsers, IconWallet,
} from '../layout/icons';
import { ROLE_LABELS } from '../lib/format';

export function MorePage() {
  const { me, company, can } = useCompany();
  const { signOut } = useAuth();
  if (!me || !company) return null;
  const admin = can('company_admin');
  const name = me.profile.full_name;
  return (
    <Stack maw={960} gap="lg">
      <Title order={3}>More</Title>
      <Paper withBorder p="md">
        <Group wrap="nowrap">
          <Avatar size={48} radius="xl" color="brand" variant="light">
            {name.split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase()}
          </Avatar>
          <Box style={{ minWidth: 0 }}>
            <Text fw={700} truncate>{name}</Text>
            <Text size="sm" c="dimmed" truncate>{me.profile.email}</Text>
            <Badge mt={6} variant="light" color="gray">{ROLE_LABELS[company.role]} · {company.code}</Badge>
          </Box>
        </Group>
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg" verticalSpacing="lg">
        <Stack gap="lg">
          <MenuGroup title="Daily work">
            <MenuRow to="/pending" label="Pending work" description="Overdue installments, drafts, approvals" icon={<IconClock />} color="orange" />
            <MenuRow to="/search" label="Search" description="Party, bill no., receipt no., amount" icon={<IconSearch />} color="blue" />
            {admin && <MenuRow to="/approvals" label="Approvals" description="Reversal requests" icon={<IconCheck />} color="grape" />}
          </MenuGroup>

          <MenuGroup title="Details & other entries">
            <MenuRow to="/entries" label="All entries" description="Every saved entry as a list" icon={<IconList />} color="indigo" />
            <MenuRow to="/bills" label="Bills & installments" icon={<IconReceipt />} color="teal" />
            {can('data_entry') && <MenuRow to="/new/payment" label="Pay a supplier" icon={<IconWallet />} color="cyan" />}
            {can('data_entry') && <MenuRow to="/new/transfer" label="Cash ↔ bank transfer" icon={<IconSwap />} color="cyan" />}
            {can('accountant') && <MenuRow to="/reconcile" label="Reconcile cash & bank" description="Match with the bank statement" icon={<IconScale />} color="green" />}
          </MenuGroup>
        </Stack>

        <Stack gap="lg">
          <MenuGroup title="Setup">
            <MenuRow to="/accounts" label="Accounts & categories" description="Cash, bank, expense types" icon={<IconBook />} color="blue" />
            {can('accountant') && <MenuRow to="/imports" label="Import from Excel" icon={<IconUpload />} color="green" />}
            {admin && <MenuRow to="/opening-balances" label="Opening balances" icon={<IconScale />} color="brand" />}
            {admin && <MenuRow to="/users" label="Employees" description="Who can sign in and what they can do" icon={<IconUsers />} color="grape" />}
            {admin && <MenuRow to="/companies" label="Companies & sites" icon={<IconBuilding />} color="gray" />}
            {admin && me.profile.is_super_admin && <MenuRow to="/backups" label="Backups" icon={<IconDatabase />} color="gray" />}
          </MenuGroup>

          <MenuGroup>
            <MenuRow onClick={signOut} label="Sign out" icon={<IconLogout />} color="red" danger />
          </MenuGroup>
        </Stack>
      </SimpleGrid>
    </Stack>
  );
}
