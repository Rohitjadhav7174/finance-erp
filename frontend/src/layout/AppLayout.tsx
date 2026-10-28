import { ActionIcon, AppShell, Badge, Box, Button, Center, Group, Loader, Menu, NavLink, Stack, Text, UnstyledButton } from '@mantine/core';
import type { ReactNode } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { CompanyPicker } from '../components/CompanyPicker';
import { BackupBanner } from '../pages/BackupsPage';
import { useCompany } from '../context/CompanyContext';
import { ROLE_LABELS } from '../lib/format';
import { IconChart, IconChevron, IconHome, IconList, IconLogout, IconMenu, IconPlus, IconSearch } from './icons';
import classes from './AppLayout.module.css';

interface NavItem { to: string; label: string; icon: ReactNode; adminOnly?: boolean }

// Main menu only — everything else lives under "More".
const MAIN_NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: <IconHome /> },
  { to: '/entry', label: 'Monthly entry', icon: <IconPlus /> },
  { to: '/register', label: 'Register', icon: <IconList /> },
  { to: '/reports', label: 'Reports', icon: <IconChart /> },
  { to: '/more', label: 'More', icon: <IconMenu /> },
];

function CompanySwitcher() {
  const { me, company, selectCompany } = useCompany();
  if (!me || !company) return null;
  return (
    <Menu position="bottom-start" width={260} disabled={me.companies.length < 2}>
      <Menu.Target>
        <UnstyledButton className={classes.companyButton} style={{ borderColor: company.theme_color }}
          aria-label={`Current company ${company.name}. Change company`}>
          <Box className={classes.companyDot} style={{ background: company.theme_color }} />
          <Text fw={700} truncate maw={180}>{company.name}</Text>
          {me.companies.length > 1 && <IconChevron size={16} />}
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        {me.companies.map((c) => (
          <Menu.Item key={c.id} onClick={() => selectCompany(c.id)}
            leftSection={<Box className={classes.companyDot} style={{ background: c.theme_color }} />}>
            {c.name}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}

export function AppLayout() {
  const { loading, error, company, can, me } = useCompany();
  const { signOut } = useAuth();
  const { pathname } = useLocation();
  const navigate = useNavigate();

  if (loading) return <Center h="100dvh"><Loader /></Center>;
  if (error || !me) {
    return (
      <Center h="100dvh" px="md">
        <Stack align="center" maw={360} ta="center">
          <Text fw={700}>Cannot open your account</Text>
          <Text c="dimmed">{error?.message ?? 'Unknown error'}</Text>
          <Button variant="light" onClick={signOut}>Sign out</Button>
        </Stack>
      </Center>
    );
  }
  if (me.companies.length === 0) {
    return (
      <Center h="100dvh" px="md">
        <Stack align="center" maw={360} ta="center">
          <Text fw={700}>No company access yet</Text>
          <Text c="dimmed">Ask your administrator to give you access to a company.</Text>
          <Button variant="light" onClick={signOut}>Sign out</Button>
        </Stack>
      </Center>
    );
  }
  if (!company) return <CompanyPicker />;

  const nav = MAIN_NAV.filter((n) => n.to !== '/entry' || can('data_entry'));
  const active = (to: string) => (to === '/' ? pathname === '/' : pathname.startsWith(to));

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: true } }}
      padding="md" className={classes.shell} style={{ '--company-color': company.theme_color } as React.CSSProperties}>
      <AppShell.Header className={classes.header}>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <CompanySwitcher />
          <Group gap="xs" wrap="nowrap">
            <Badge variant="light" color="gray" visibleFrom="xs">{ROLE_LABELS[company.role]}</Badge>
            <ActionIcon component={Link} to="/search" variant="subtle" color="gray" size="lg" aria-label="Search">
              <IconSearch />
            </ActionIcon>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm" visibleFrom="sm">
        <Stack gap={4} h="100%">
          {nav.map((n) => (
            <NavLink key={n.to} component={Link} to={n.to} label={n.label} leftSection={n.icon} active={active(n.to)} />
          ))}
          <Box mt="auto" />
          <Text size="sm" fw={600} truncate>{me.profile.full_name}</Text>
          <NavLink label="Sign out" leftSection={<IconLogout />} onClick={signOut} />
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main className={classes.main}>
        <BackupBanner />
        <Outlet />
      </AppShell.Main>

      {/* Mobile bottom navigation */}
      <nav className={classes.bottomNav} aria-label="Main">
        <BottomLink to="/" label="Dashboard" icon={<IconHome />} active={active('/')} />
        <BottomLink to="/register" label="Register" icon={<IconList />} active={active('/register')} />
        {can('data_entry') ? (
          <button type="button" className={classes.fab} onClick={() => navigate('/entry')} aria-label="New monthly entry"
            style={{ background: company.theme_color }}>
            <IconPlus size={28} />
          </button>
        ) : <span className={classes.fabSpacer} />}
        <BottomLink to="/reports" label="Reports" icon={<IconChart />} active={active('/reports')} />
        <BottomLink to="/more" label="More" icon={<IconMenu />} active={!['/', '/register', '/reports', '/entry'].some((p) => p === '/' ? pathname === '/' : pathname.startsWith(p))} />
      </nav>
    </AppShell>
  );
}

function BottomLink({ to, label, icon, active }: { to: string; label: string; icon: ReactNode; active: boolean }) {
  return (
    <Link to={to} className={classes.bottomLink} data-active={active || undefined} aria-current={active ? 'page' : undefined}>
      {icon}
      <span>{label}</span>
    </Link>
  );
}
