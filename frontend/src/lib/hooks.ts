import { useQuery } from '@tanstack/react-query';
import { useCompany } from '../context/CompanyContext';
import { api } from './api';

export interface Account {
  id: string; code: string; name: string; type: string; subtype: string;
  bank_name: string | null; account_no_last4: string | null; is_system: boolean; is_active: boolean; balance: string;
}
export interface Party {
  id: string; name: string; kind: string; phone: string | null; is_active: boolean; version: number;
  receivable_balance: string; payable_balance: string;
}
export interface Site { id: string; name: string; is_active: boolean }

export interface Bill {
  id: string; bill_no: string; direction: 'receivable' | 'payable'; party_id: string; party_name: string;
  bill_date: string; due_date: string | null; period_from: string | null; period_to: string | null;
  amount: string; paid: string; outstanding: string; pending_payments: string; pay_status: string;
  description: string; notes: string | null; status: string; version: number; journal_entry_id: string;
  next_installment_date: string | null;
}

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export function useAccounts() {
  const { company } = useCompany();
  return useQuery({
    queryKey: ['accounts', company?.id],
    queryFn: () => api<Account[]>(`/companies/${company!.id}/accounts`),
    enabled: !!company,
  });
}

export function useParties() {
  const { company } = useCompany();
  return useQuery({
    queryKey: ['parties', company?.id],
    queryFn: () => api<Party[]>(`/companies/${company!.id}/parties`),
    enabled: !!company,
  });
}

export function useSites() {
  const { company } = useCompany();
  return useQuery({
    queryKey: ['sites', company?.id],
    queryFn: () => api<Site[]>(`/companies/${company!.id}/sites`),
    enabled: !!company,
  });
}

export function useOpenBills(partyId: string | null, direction: 'receivable' | 'payable') {
  const { company } = useCompany();
  return useQuery({
    queryKey: ['open-bills', company?.id, partyId, direction],
    queryFn: () => api<Page<Bill>>(
      `/companies/${company!.id}/bills?open_only=true&direction=${direction}&party_id=${partyId}&sort=due_date&page_size=100`),
    enabled: !!company && !!partyId,
  });
}

export const moneyAccounts = (a?: Account[]) => (a ?? []).filter((x) => x.is_active && ['cash', 'bank'].includes(x.subtype));
export const byType = (a: Account[] | undefined, type: string) => (a ?? []).filter((x) => x.is_active && x.type === type);
export const accountLabel = (a: Account) =>
  a.subtype === 'bank' && a.account_no_last4 ? `${a.name} ••${a.account_no_last4}` : a.name;
