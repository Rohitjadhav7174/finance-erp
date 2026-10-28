-- 0005 — Row Level Security on every table + least-privilege grants for app_api.
--
-- Every policy is written for role app_api (the backend). anon/authenticated have
-- no privileges on schema fin at all. Policies are fail-closed: with no JWT claims,
-- fin.uid() is NULL and every helper returns false.

-- ---------------------------------------------------------------------------
-- Extra policy helpers
-- ---------------------------------------------------------------------------
create function fin.shares_company(p_user uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select fin.is_super_admin() or exists (
    select 1 from fin.company_memberships m
    where m.user_id = p_user and fin.company_role(m.company_id) is not null
  )
$$;

create function fin.can_manage_user(p_user uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select fin.is_super_admin() or exists (
    select 1 from fin.company_memberships m
    where m.user_id = p_user and fin.has_role(m.company_id, 'company_admin')
  )
$$;

create function fin.is_company_admin_anywhere() returns boolean
language sql stable security definer set search_path = '' as $$
  select fin.is_super_admin() or exists (
    select 1 from fin.company_memberships m
    where m.user_id = fin.uid() and fin.company_role(m.company_id) = 'company_admin'
  )
$$;

-- Draft/pending entry the current user may edit: accountants+ any, data entry own only.
create function fin.can_edit_entry(p_entry uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from fin.journal_entries e
    where e.id = p_entry and e.status in ('draft', 'pending_approval')
      and (fin.has_role(e.company_id, 'accountant')
           or (fin.has_role(e.company_id, 'data_entry') and e.created_by = fin.uid()))
  )
$$;

-- ---------------------------------------------------------------------------
-- Enable RLS everywhere
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'companies', 'sites', 'profiles', 'company_memberships', 'audit_log', 'security_events',
    'accounts', 'parties', 'financial_periods', 'doc_counters', 'journal_entries', 'journal_lines',
    'approval_requests', 'bills', 'installment_schedule', 'bill_allocations', 'follow_ups',
    'attachments', 'reconciliations', 'import_batches', 'import_rows', 'backup_runs', 'system_settings']
  loop
    execute format('alter table fin.%I enable row level security', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- Identity
-- ---------------------------------------------------------------------------
create policy companies_select on fin.companies for select to app_api
  using (fin.is_super_admin() or fin.company_role(id) is not null);
create policy companies_insert on fin.companies for insert to app_api
  with check (fin.is_super_admin());
create policy companies_update on fin.companies for update to app_api
  using (fin.is_super_admin()) with check (fin.is_super_admin());

create policy sites_select on fin.sites for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy sites_write on fin.sites for insert to app_api
  with check (fin.has_role(company_id, 'company_admin'));
create policy sites_update on fin.sites for update to app_api
  using (fin.has_role(company_id, 'company_admin')) with check (fin.has_role(company_id, 'company_admin'));

create policy profiles_select on fin.profiles for select to app_api
  using (user_id = fin.uid() or fin.shares_company(user_id));
create policy profiles_insert on fin.profiles for insert to app_api
  with check (fin.is_company_admin_anywhere());
create policy profiles_update on fin.profiles for update to app_api
  using (user_id = fin.uid() or fin.can_manage_user(user_id))
  with check (user_id = fin.uid() or fin.can_manage_user(user_id));

create policy memberships_select on fin.company_memberships for select to app_api
  using (user_id = fin.uid() or fin.has_role(company_id, 'company_admin'));
create policy memberships_insert on fin.company_memberships for insert to app_api
  with check (fin.has_role(company_id, 'company_admin'));
create policy memberships_update on fin.company_memberships for update to app_api
  using (fin.has_role(company_id, 'company_admin')) with check (fin.has_role(company_id, 'company_admin'));

create policy audit_select on fin.audit_log for select to app_api
  using (fin.is_super_admin() or (company_id is not null and fin.has_role(company_id, 'company_admin')));

create policy security_events_select on fin.security_events for select to app_api
  using (fin.is_super_admin());
create policy security_events_insert on fin.security_events for insert to app_api
  with check (true);

-- ---------------------------------------------------------------------------
-- Ledger
-- ---------------------------------------------------------------------------
create policy accounts_select on fin.accounts for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy accounts_insert on fin.accounts for insert to app_api
  with check (fin.has_role(company_id, 'accountant'));
create policy accounts_update on fin.accounts for update to app_api
  using (fin.has_role(company_id, 'accountant')) with check (fin.has_role(company_id, 'accountant'));

create policy parties_select on fin.parties for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy parties_insert on fin.parties for insert to app_api
  with check (fin.has_role(company_id, 'data_entry'));
create policy parties_update on fin.parties for update to app_api
  using (fin.has_role(company_id, 'accountant')) with check (fin.has_role(company_id, 'accountant'));

create policy periods_select on fin.financial_periods for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy periods_update on fin.financial_periods for update to app_api
  using (fin.has_role(company_id, 'company_admin')) with check (fin.has_role(company_id, 'company_admin'));

create policy entries_select on fin.journal_entries for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy entries_insert on fin.journal_entries for insert to app_api
  with check (fin.has_role(company_id, 'data_entry'));
create policy entries_update on fin.journal_entries for update to app_api
  using (fin.has_role(company_id, 'accountant')
         or (fin.has_role(company_id, 'data_entry') and created_by = fin.uid()
             and status in ('draft', 'pending_approval')))
  with check (fin.has_role(company_id, 'accountant')
         or (fin.has_role(company_id, 'data_entry') and created_by = fin.uid()
             and status in ('draft', 'pending_approval')));
create policy entries_delete on fin.journal_entries for delete to app_api
  using (fin.can_edit_entry(id));

create policy lines_select on fin.journal_lines for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy lines_insert on fin.journal_lines for insert to app_api
  with check (fin.can_edit_entry(entry_id));
create policy lines_update on fin.journal_lines for update to app_api
  using (fin.can_edit_entry(entry_id) or fin.has_role(company_id, 'accountant'))
  with check (fin.can_edit_entry(entry_id) or fin.has_role(company_id, 'accountant'));
create policy lines_delete on fin.journal_lines for delete to app_api
  using (fin.can_edit_entry(entry_id));

create policy approvals_select on fin.approval_requests for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy approvals_insert on fin.approval_requests for insert to app_api
  with check (fin.has_role(company_id, 'accountant'));
create policy approvals_update on fin.approval_requests for update to app_api
  using (fin.has_role(company_id, 'accountant')) with check (fin.has_role(company_id, 'accountant'));

-- ---------------------------------------------------------------------------
-- Bills
-- ---------------------------------------------------------------------------
create policy bills_select on fin.bills for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy bills_insert on fin.bills for insert to app_api
  with check (fin.has_role(company_id, 'data_entry'));
create policy bills_update on fin.bills for update to app_api
  using (fin.has_role(company_id, 'accountant')
         or (fin.has_role(company_id, 'data_entry') and created_by = fin.uid() and status = 'draft'))
  with check (fin.has_role(company_id, 'accountant')
         or (fin.has_role(company_id, 'data_entry') and created_by = fin.uid() and status = 'draft'));
create policy bills_delete on fin.bills for delete to app_api
  using (status = 'draft' and (fin.has_role(company_id, 'accountant')
         or (fin.has_role(company_id, 'data_entry') and created_by = fin.uid())));

create policy installments_select on fin.installment_schedule for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy installments_insert on fin.installment_schedule for insert to app_api
  with check (fin.has_role(company_id, 'accountant'));
create policy installments_update on fin.installment_schedule for update to app_api
  using (fin.has_role(company_id, 'accountant')) with check (fin.has_role(company_id, 'accountant'));
create policy installments_delete on fin.installment_schedule for delete to app_api
  using (fin.has_role(company_id, 'accountant'));

create policy allocations_select on fin.bill_allocations for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy allocations_insert on fin.bill_allocations for insert to app_api
  with check (fin.can_edit_entry(entry_id));
create policy allocations_delete on fin.bill_allocations for delete to app_api
  using (fin.can_edit_entry(entry_id));

-- ---------------------------------------------------------------------------
-- Operations
-- ---------------------------------------------------------------------------
create policy followups_select on fin.follow_ups for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy followups_insert on fin.follow_ups for insert to app_api
  with check (fin.has_role(company_id, 'data_entry'));
create policy followups_update on fin.follow_ups for update to app_api
  using (fin.has_role(company_id, 'accountant')
         or (fin.has_role(company_id, 'data_entry') and fin.uid() in (created_by, assigned_to)))
  with check (fin.has_role(company_id, 'data_entry'));

create policy attachments_select on fin.attachments for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy attachments_insert on fin.attachments for insert to app_api
  with check (fin.has_role(company_id, 'data_entry'));

create policy reconciliations_select on fin.reconciliations for select to app_api
  using (fin.has_role(company_id, 'viewer'));
create policy reconciliations_insert on fin.reconciliations for insert to app_api
  with check (fin.has_role(company_id, 'accountant'));
create policy reconciliations_update on fin.reconciliations for update to app_api
  using (fin.has_role(company_id, 'accountant')) with check (fin.has_role(company_id, 'accountant'));

create policy import_batches_all on fin.import_batches for all to app_api
  using (fin.has_role(company_id, 'accountant')) with check (fin.has_role(company_id, 'accountant'));
create policy import_rows_all on fin.import_rows for all to app_api
  using (fin.has_role(company_id, 'accountant')) with check (fin.has_role(company_id, 'accountant'));

create policy backup_runs_select on fin.backup_runs for select to app_api
  using (fin.is_super_admin());

create policy settings_select on fin.system_settings for select to app_api
  using (fin.uid() is not null);
create policy settings_update on fin.system_settings for update to app_api
  using (fin.is_super_admin()) with check (fin.is_super_admin());

-- doc_counters: no policy => no direct access (written only by fin.next_entry_no).

-- ---------------------------------------------------------------------------
-- Grants (table privileges are the outer gate; RLS is the inner gate)
-- ---------------------------------------------------------------------------
grant select, insert, update on fin.companies, fin.sites, fin.profiles, fin.company_memberships,
  fin.accounts, fin.parties, fin.approval_requests, fin.installment_schedule, fin.follow_ups,
  fin.reconciliations, fin.import_batches, fin.import_rows to app_api;
grant select, update on fin.financial_periods, fin.system_settings to app_api;
grant select, insert, update, delete on fin.journal_entries, fin.journal_lines, fin.bills to app_api;
grant delete on fin.installment_schedule, fin.import_rows to app_api;
grant select, insert, delete on fin.bill_allocations to app_api;
grant select, insert on fin.attachments, fin.security_events to app_api;
grant select on fin.audit_log, fin.backup_runs to app_api;

-- Functions app_api needs (directly or because invoker-rights triggers/policies call them).
grant execute on function
  fin.is_trusted_console(), fin.fy_label(date, integer), fin.ensure_period(uuid, date),
  fin.next_entry_no(uuid, date), fin.consume_approval(uuid, fin.approval_action, uuid),
  fin.validate_posting(fin.journal_entries), fin.reversal_mismatches(uuid, uuid),
  fin.bill_balances(uuid, date), fin.shares_company(uuid), fin.can_manage_user(uuid),
  fin.is_company_admin_anywhere(), fin.can_edit_entry(uuid)
to app_api;

-- Defensive: make sure the public API roles can never reach the fin schema.
do $$
declare r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on all tables in schema fin from %I', r);
      execute format('revoke all on all functions in schema fin from %I', r);
      execute format('revoke all on all sequences in schema fin from %I', r);
    end if;
  end loop;
end $$;
revoke all on all functions in schema fin from public;
grant execute on function fin.uid(), fin.role_rank(fin.app_role), fin.is_super_admin(),
  fin.company_role(uuid), fin.has_role(uuid, fin.app_role), fin.is_trusted_console(),
  fin.fy_label(date, integer), fin.ensure_period(uuid, date), fin.next_entry_no(uuid, date),
  fin.consume_approval(uuid, fin.approval_action, uuid), fin.validate_posting(fin.journal_entries),
  fin.reversal_mismatches(uuid, uuid), fin.bill_balances(uuid, date), fin.shares_company(uuid),
  fin.can_manage_user(uuid), fin.is_company_admin_anywhere(), fin.can_edit_entry(uuid)
to app_api;
