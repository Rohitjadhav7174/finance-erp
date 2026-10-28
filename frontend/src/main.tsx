import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import './design.css';

import { Center, Loader, MantineProvider, createTheme, type CSSVariablesResolver } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { ForgotPasswordPage, LoginPage, SetPasswordPage } from './auth/AuthPages';
import { AuthProvider, useAuth } from './auth/AuthProvider';
import { CompanyProvider, useCompany } from './context/CompanyContext';
import { AppLayout } from './layout/AppLayout';
import { ApiError } from './lib/api';
import { AccountsPage } from './pages/AccountsPage';
import { BackupsPage } from './pages/BackupsPage';
import { ImportDetailPage, ImportsPage } from './pages/ImportsPage';
import { ReconcileListPage, ReconcilePage } from './pages/ReconcilePage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { BillDetailPage, BillsPage } from './pages/BillsPage';
import { CompaniesPage } from './pages/CompaniesPage';
import { EntriesPage } from './pages/EntriesPage';
import { EntryDetailPage } from './pages/EntryDetailPage';
import { EntryFormPage } from './pages/EntryFormPage';
import { HomePage } from './pages/HomePage';
import { MonthlyEntryPage } from './pages/MonthlyEntryPage';
import { MorePage } from './pages/MorePage';
import { RegisterPage } from './pages/RegisterPage';
import { OpeningBalancesPage } from './pages/OpeningBalancesPage';
import { PendingPage } from './pages/PendingPage';
import { ReportsPage, ReportViewPage } from './pages/ReportsPage';
import { SearchPage } from './pages/SearchPage';
import { UsersPage } from './pages/UsersPage';

// Accessibility (WCAG AA, 4.5:1 for small text): one shade darker than Mantine's default for
// every colour, and a darker "dimmed" grey (#868e96 is only 3.3:1 on white).
const theme = createTheme({
  fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif',
  defaultRadius: 'md',
  primaryColor: 'blue',
  primaryShade: { light: 8, dark: 6 },
  headings: { fontWeight: '700' },
  components: {
    Paper: { defaultProps: { radius: 'lg' } },
    Button: { defaultProps: { radius: 'md' } },
    Badge: { defaultProps: { radius: 'sm' } },
  },
});

// Text on tinted ("light" variant) badges, alerts and buttons uses shade 9 so it stays >= 4.5:1.
const LIGHT_TEXT: Record<string, string> = {
  blue: '#1864ab', red: '#c92a2a', orange: '#a63a06', yellow: '#7a5200', green: '#1e6b30', teal: '#087f5b',
  cyan: '#0b7285', grape: '#862e9c', gray: '#495057', violet: '#5f3dc4',
};
const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    '--mantine-color-dimmed': '#5c636a',
    '--mantine-color-anchor': '#1864ab',
    ...Object.fromEntries(Object.entries(LIGHT_TEXT).map(([c, v]) => [`--mantine-color-${c}-light-color`, v])),
  },
  dark: {},
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
});

function RequireAuth() {
  const { session, loading } = useAuth();
  if (loading) return <Center h="100dvh"><Loader /></Center>;
  if (!session) return <Navigate to="/login" replace />;
  return (
    <CompanyProvider>
      <Outlet />
    </CompanyProvider>
  );
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { can } = useCompany();
  return can('company_admin') ? <>{children}</> : <Navigate to="/" replace />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} cssVariablesResolver={cssVariablesResolver} defaultColorScheme="light">
      <Notifications position="top-center" />
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/set-password" element={<SetPasswordPage />} />
              <Route element={<RequireAuth />}>
                <Route element={<AppLayout />}>
                  <Route index element={<HomePage />} />
                  <Route path="entry" element={<MonthlyEntryPage />} />
                  <Route path="register" element={<RegisterPage />} />
                  <Route path="entries" element={<EntriesPage />} />
                  <Route path="entries/:id" element={<EntryDetailPage />} />
                  <Route path="entries/:id/edit" element={<EntryFormPage />} />
                  <Route path="new/:kind" element={<EntryFormPage />} />
                  <Route path="bills" element={<BillsPage />} />
                  <Route path="bills/:id" element={<BillDetailPage />} />
                  <Route path="accounts" element={<AccountsPage />} />
                  <Route path="approvals" element={<RequireAdmin><ApprovalsPage /></RequireAdmin>} />
                  <Route path="pending" element={<PendingPage />} />
                  <Route path="reports" element={<ReportsPage />} />
                  <Route path="reports/:name" element={<ReportViewPage />} />
                  <Route path="search" element={<SearchPage />} />
                  <Route path="imports" element={<ImportsPage />} />
                  <Route path="imports/:id" element={<ImportDetailPage />} />
                  <Route path="reconcile" element={<ReconcileListPage />} />
                  <Route path="reconcile/:id" element={<ReconcilePage />} />
                  <Route path="backups" element={<BackupsPage />} />
                  <Route path="opening-balances" element={<RequireAdmin><OpeningBalancesPage /></RequireAdmin>} />
                  <Route path="more" element={<MorePage />} />
                  <Route path="users" element={<RequireAdmin><UsersPage /></RequireAdmin>} />
                  <Route path="companies" element={<RequireAdmin><CompaniesPage /></RequireAdmin>} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Route>
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </MantineProvider>
  </React.StrictMode>,
);
