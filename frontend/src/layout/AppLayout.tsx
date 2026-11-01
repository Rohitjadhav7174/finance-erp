import { ActionIcon, AppShell, Avatar, Box, Button, Center, Group, Loader, Menu, Stack, Text, UnstyledButton } from '@mantine/core';
import type { ReactNode } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { CompanyPicker } from '../components/CompanyPicker';
import { BackupBanner } from '../pages/BackupsPage';
import { useCompany } from '../context/CompanyContext';
import { ROLE_LABELS } from '../lib/format';
import { IconChart, IconCheck, IconChevron, IconHome, IconList, IconLogout, IconMenu, IconPlus, IconSearch } from './icons';
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

const initials = (name: string) => name.split(/\s+/).filter((w) => /^[A-Za-z]/.test(w)).slice(0, 2).map((w) => w[0]).join('').toUpperCase();

function CompanySwitcher() {
  const { me, company, selectCompany } = useCompany();
  if (!me || !company) return null;
  return (
    <Menu position="bottom-start" width={280} disabled={me.companies.length < 2}>
      <Menu.Target>
        <UnstyledButton className={classes.companyButton} aria-label={`Current company ${company.name}. Change company`}>
          <span className={classes.brandMark} style={{ background: company.theme_color }}>{company.code}</span>
          <Box style={{ minWidth: 0 }}>
            <Text fw={700} size="sm" truncate maw={200} lh={1.2}>{company.name}</Text>
            <Text size="xs" c="dimmed" lh={1.2}>{ROLE_LABELS[company.role]}</Text>
          </Box>
          {me.companies.length > 1 && <IconChevron size={16} className={classes.chevron} />}
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Switch company</Menu.Label>
        {me.companies.map((c) => (
          <Menu.Item key={c.id} onClick={() => selectCompany(c.id)}
            leftSection={<span className={classes.brandMarkSmall} style={{ background: c.theme_color }}>{c.code}</span>}
            rightSection={c.id === company.id ? <IconCheck size={16} /> : null}>
            {c.name}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}

function UserMenu() {
  const { me, company } = useCompany();
  const { signOut } = useAuth();
  if (!me || !company) return null;
  return (
    <Menu position="bottom-end" width={240}>
      <Menu.Target>
        <UnstyledButton aria-label="Your account">
          <Avatar size={34} radius="xl" color={company.theme_color} variant="light">{initials(me.profile.full_name)}</Avatar>
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Box px="sm" py={6}>
          <Text size="sm" fw={600} truncate>{me.profile.full_name}</Text>
          <Text size="xs" c="dimmed" truncate>{me.profile.email}</Text>
        </Box>
        <Menu.Divider />
        <Menu.Item component={Link} to="/more" leftSection={<IconMenu size={16} />}>All menus</Menu.Item>
        <Menu.Item color="red" leftSection={<IconLogout size={16} />} onClick={signOut}>Sign out</Menu.Item>
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
    <AppShell header={{ height: 60 }} navbar={{ width: 248, breakpoint: 'sm', collapsed: { mobile: true } }}
      padding="md" className={classes.shell} style={{ '--company-color': company.theme_color } as React.CSSProperties}>
      <AppShell.Header className={classes.header}>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <CompanySwitcher />
          <Group gap={6} wrap="nowrap">
            <ActionIcon component={Link} to="/search" variant="subtle" color="gray" size="lg" radius="xl" aria-label="Search">
              <IconSearch size={20} />
            </ActionIcon>
            <UserMenu />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm" visibleFrom="sm" className={classes.navbar}>
        <Stack gap={2} h="100%">
          <Text className={classes.navLabel}>Menu</Text>
          {nav.map((n) => (
            <UnstyledButton key={n.to} component={Link} to={n.to} className={classes.navItem}
              data-active={active(n.to) || undefined} aria-current={active(n.to) ? 'page' : undefined}>
              {n.icon}<span>{n.label}</span>
            </UnstyledButton>
          ))}
          <Box mt="auto" className={classes.navUser}>
            <Avatar size={32} radius="xl" color={company.theme_color} variant="light">{initials(me.profile.full_name)}</Avatar>
            <Box style={{ minWidth: 0, flex: 1 }}>
              <Text size="sm" fw={600} truncate>{me.profile.full_name}</Text>
              <Text size="xs" c="dimmed" truncate>{ROLE_LABELS[company.role]}</Text>
            </Box>
            <ActionIcon variant="subtle" color="gray" onClick={signOut} aria-label="Sign out"><IconLogout size={18} /></ActionIcon>
          </Box>
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
            data-active={active('/entry') || undefined}>
            <span style={{ background: company.theme_color }}><IconPlus size={22} /></span>
            Entry
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
