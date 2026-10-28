-- 0007 — Phase 5: backup fingerprint, reconciliation rules.

-- ---------------------------------------------------------------------------
-- Backup fingerprint: row counts and money totals that must match exactly after a
-- restore. Callable by a super admin (through the API) or by the backup job, which
-- connects with the database owner credentials from the CI secret store.
-- ---------------------------------------------------------------------------
create function fin.backup_fingerprint() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare
  v_tables jsonb := '{}'::jsonb;
  v_count bigint;
  t text;
begin
  if fin.uid() is not null and not fin.is_super_admin() then
    raise exception 'only a super admin can read the backup fingerprint' using errcode = '42501';
  end if;
  if fin.uid() is null and current_user = 'app_api' then
    raise exception 'not authenticated' using errcode = '42501';
  end if;
  foreach t in array array[
    'companies', 'sites', 'profiles', 'company_memberships', 'accounts', 'parties', 'financial_periods',
    'journal_entries', 'journal_lines', 'bills', 'installment_schedule', 'bill_allocations', 'approval_requests',
    'follow_ups', 'attachments', 'reconciliations', 'import_batches', 'import_rows', 'audit_log', 'security_events']
  loop
    execute format('select count(*) from fin.%I', t) into v_count;
    v_tables := v_tables || jsonb_build_object(t, v_count);
  end loop;
  return jsonb_build_object(
    'tables', v_tables,
    'companies', coalesce((
      select jsonb_object_agg(c.code, jsonb_build_object(
        'debits', coalesce((select sum(l.debit) from fin.journal_lines l where l.company_id = c.id), 0)::text,
        'credits', coalesce((select sum(l.credit) from fin.journal_lines l where l.company_id = c.id), 0)::text,
        'posted_entries', (select count(*) from fin.journal_entries e where e.company_id = c.id and e.status = 'posted'),
        'bills_total', coalesce((select sum(b.amount) from fin.bills b where b.company_id = c.id), 0)::text,
        'allocations_total', coalesce((select sum(a.amount) from fin.bill_allocations a where a.company_id = c.id), 0)::text,
        'last_entry_no', (select max(e.entry_no) from fin.journal_entries e where e.company_id = c.id)))
      from fin.companies c), '{}'::jsonb),
    'audit_last_id', (select coalesce(max(id), 0) from fin.audit_log)
  );
end $$;
grant execute on function fin.backup_fingerprint() to app_api;

-- ---------------------------------------------------------------------------
-- Reconciliation rules
-- ---------------------------------------------------------------------------
create function fin.tg_reconciliations_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    if new.status <> 'in_progress' then
      raise exception 'start a reconciliation as in progress' using errcode = 'P0001';
    end if;
    if not exists (select 1 from fin.accounts a where a.id = new.account_id and a.subtype in ('cash', 'bank')) then
      raise exception 'only cash and bank accounts can be reconciled' using errcode = 'P0001';
    end if;
    new.created_by := coalesce(fin.uid(), new.created_by);
    return new;
  end if;
  if old.status = 'completed' then
    raise exception 'a completed reconciliation cannot be changed' using errcode = '42501';
  end if;
  if (new.company_id, new.account_id) is distinct from (old.company_id, old.account_id) then
    raise exception 'account of a reconciliation cannot change' using errcode = 'P0001';
  end if;
  if new.status = 'completed' then
    if new.difference is distinct from 0 then
      raise exception 'the cleared balance must equal the statement balance before completing' using errcode = 'P0001';
    end if;
    new.completed_by := fin.uid();
    new.completed_at := now();
  end if;
  return new;
end $$;
create trigger tg_guard before insert or update on fin.reconciliations
  for each row execute function fin.tg_reconciliations_guard();

-- A line may only be ticked into an in-progress reconciliation of its own account, and lines
-- of a completed reconciliation stay reconciled.
create function fin.tg_lines_reconcile_guard() returns trigger
language plpgsql set search_path = '' as $$
declare
  v_rec fin.reconciliations;
begin
  if new.reconciliation_id is not distinct from old.reconciliation_id
     and new.reconciled_at is not distinct from old.reconciled_at then
    return new;
  end if;
  if old.reconciliation_id is not null and exists (
       select 1 from fin.reconciliations r where r.id = old.reconciliation_id and r.status = 'completed') then
    raise exception 'this line belongs to a completed reconciliation' using errcode = '42501';
  end if;
  if new.reconciliation_id is not null then
    select * into v_rec from fin.reconciliations where id = new.reconciliation_id;
    if v_rec.status <> 'in_progress' or v_rec.account_id <> new.account_id then
      raise exception 'line does not belong to this reconciliation''s account' using errcode = 'P0001';
    end if;
  end if;
  return new;
end $$;
create trigger tg_reconcile_guard before update of reconciliation_id, reconciled_at on fin.journal_lines
  for each row execute function fin.tg_lines_reconcile_guard();

-- ---------------------------------------------------------------------------
-- One Excel row can hold several transactions (e.g. a receipt in column C and an
-- expense in D/E on the same line), so import rows are keyed by (sheet, row, part).
-- ---------------------------------------------------------------------------
alter table fin.import_rows add column part smallint not null default 1 check (part between 1 and 20);
alter table fin.import_rows drop constraint import_rows_batch_id_sheet_row_number_key;
alter table fin.import_rows add constraint import_rows_batch_sheet_row_part_key unique (batch_id, sheet, row_number, part);

-- An in-progress reconciliation may be abandoned (deleted, audited); a completed one never.
grant delete on fin.reconciliations to app_api;
create policy reconciliations_delete on fin.reconciliations for delete to app_api
  using (fin.has_role(company_id, 'accountant') and status = 'in_progress');
create function fin.tg_reconciliations_delete_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if old.status = 'completed' then
    raise exception 'a completed reconciliation cannot be removed' using errcode = '42501';
  end if;
  update fin.journal_lines set reconciliation_id = null where reconciliation_id = old.id;
  return old;
end $$;
create trigger tg_delete_guard before delete on fin.reconciliations
  for each row execute function fin.tg_reconciliations_delete_guard();

-- Backup health for the admin warning banner (status only, no backup details).
create function fin.backup_health() returns jsonb
language sql stable security definer set search_path = '' as $$
  select case when not (fin.is_super_admin() or fin.is_company_admin_anywhere()) then null else
    jsonb_build_object(
      'last_success_at', (select max(finished_at) from fin.backup_runs where status in ('succeeded', 'verified')),
      'last_verified_at', (select max(verified_at) from fin.backup_runs where status = 'verified'),
      'last_status', (select status::text from fin.backup_runs order by started_at desc limit 1),
      'last_error_at', (select max(finished_at) from fin.backup_runs where status = 'failed'),
      'max_age_hours', (select (value #>> '{}')::int from fin.system_settings where key = 'backup.max_age_hours'),
      'overdue', coalesce((select max(finished_at) from fin.backup_runs where status in ('succeeded', 'verified'))
                   < now() - make_interval(hours => (select (value #>> '{}')::int from fin.system_settings
                                                      where key = 'backup.max_age_hours')), true)
    ) end
$$;
grant execute on function fin.backup_health() to app_api;
