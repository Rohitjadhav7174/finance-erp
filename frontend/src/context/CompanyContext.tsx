import { useQuery } from '@tanstack/react-query';
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '../lib/api';

export type Role = 'super_admin' | 'company_admin' | 'accountant' | 'data_entry' | 'viewer';

export interface CompanyAccess {
  id: string;
  code: string;
  name: string;
  theme_color: string;
  fy_start_month: number;
  role: Role;
}

export interface Me {
  profile: {
    user_id: string;
    full_name: string;
    email: string;
    phone: string | null;
    is_super_admin: boolean;
    can_view_consolidated: boolean;
    version: number;
  };
  companies: CompanyAccess[];
}

const RANK: Record<Role, number> = { viewer: 1, data_entry: 2, accountant: 3, company_admin: 4, super_admin: 5 };

interface CompanyState {
  me: Me | undefined;
  loading: boolean;
  error: Error | null;
  company: CompanyAccess | null;
  selectCompany: (id: string) => void;
  /** UI convenience only — the server and database enforce the real permissions. */
  can: (min: Role) => boolean;
}

const Ctx = createContext<CompanyState | null>(null);
const STORAGE_KEY = 'erp.company'; // remembers the last-used company on this device (not sensitive)

export function CompanyProvider({ children }: { children: ReactNode }) {
  const { data: me, isLoading, error } = useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/me') });
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  });

  const company = useMemo(() => {
    if (!me) return null;
    const found = me.companies.find((c) => c.id === selectedId);
    // Auto-select only when exactly one company is available; otherwise the user must choose.
    return found ?? (me.companies.length === 1 ? me.companies[0] : null);
  }, [me, selectedId]);

  useEffect(() => {
    if (company) document.querySelector('meta[name=theme-color]')?.setAttribute('content', company.theme_color);
  }, [company]);

  const selectCompany = (id: string) => {
    setSelectedId(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* storage unavailable (private mode) — selection still works for this session */
    }
  };

  const can = (min: Role) => !!company && RANK[company.role] >= RANK[min];

  return (
    <Ctx.Provider value={{ me, loading: isLoading, error: error as Error | null, company, selectCompany, can }}>
      {children}
    </Ctx.Provider>
  );
}

export function useCompany(): CompanyState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useCompany outside CompanyProvider');
  return ctx;
}
