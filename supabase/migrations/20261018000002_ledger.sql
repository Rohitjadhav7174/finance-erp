-- 0002 — Double-entry ledger: accounts, parties, periods, journal entries/lines.
--
-- Integrity rules enforced here (independent of the API):
--   * Same-company references via composite foreign keys (company_id, id).
--   * Entries are created as draft/pending; they become `posted` only via a status
--     change that validates: role, balanced lines, open period, cash/bank rules.
--   * Posted entries and their lines are immutable. The only permitted change is
--     posted -> reversed, which requires an approved reversal entry.
--   * Entry numbers are assigned at posting time, gap-free per company & FY.
--   * Duplicate receipt/payment reference numbers are rejected.

create type fin.account_type as enum ('asset', 'liability', 'equity', 'income', 'expense');
create type fin.account_subtype as enum
  ('cash', 'bank', 'receivable', 'payable', 'customer_advance', 'opening_equity', 'other');
create type fin.party_kind as enum ('customer', 'supplier', 'employee', 'other');
create type fin.period_status as enum ('open', 'closed');
create type fin.entry_type as enum
  ('bill_sale', 'bill_purchase', 'receipt', 'payment', 'expense', 'transfer',
   'opening', 'adjustment', 'reversal');
create type fin.entry_status as enum ('draft', 'pending_approval', 'posted', 'reversed');
create type fin.payment_method as enum ('cash', 'bank_transfer', 'upi', 'cheque', 'other');
create type fin.entry_source as enum ('manual', 'import');

-- ---------------------------------------------------------------------------
-- Accounts (chart of accounts; cash & bank accounts are accounts too)
-- ---------------------------------------------------------------------------
create table fin.accounts (
  id               uuid primary key default gen_random_uuid(),
  company_id       uuid not null references fin.companies (id),
  code             text not null check (code ~ '^[A-Z0-9-]{2,20}$'),
  name             text not null check (length(trim(name)) between 1 and 120),
  type             fin.account_type not null,
  subtype          fin.account_subtype not null default 'other',
  bank_name        text,
  account_no_last4 text check (account_no_last4 is null or account_no_last4 ~ '^[0-9]{4}$'),
  is_system        boolean not null default false,
  is_active        boolean not null default true,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  version          integer not null default 1,
  unique (company_id, code),
  unique (company_id, id),
  check (subtype not in ('cash', 'bank', 'receivable') or type = 'asset'),
  check (subtype not in ('payable', 'customer_advance') or type = 'liability'),
  check (subtype <> 'opening_equity' or type = 'equity')
);

create table fin.parties (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null references fin.companies (id),
  name       text not null check (length(trim(name)) between 1 and 200),
  kind       fin.party_kind not null,
  phone      text,
  gstin      text check (gstin is null or gstin ~ '^[0-9A-Z]{15}$'),
  notes      text check (notes is null or length(notes) <= 2000),
  is_active  boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version    integer not null default 1,
  unique (company_id, id)
);
create unique index ux_parties_name on fin.parties (company_id, lower(trim(name)));

-- ---------------------------------------------------------------------------
-- Financial periods (monthly) and financial-year helpers
-- ---------------------------------------------------------------------------
create table fin.financial_periods (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null references fin.companies (id),
  start_date date not null check (extract(day from start_date) = 1),
  end_date   date not null,
  label      text not null,
  fy_label   text not null,
  status     fin.period_status not null default 'open',
  closed_by  uuid,
  closed_at  timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version    integer not null default 1,
  unique (company_id, start_date),
  unique (company_id, id),
  check (end_date = (start_date + interval '1 month - 1 day')::date)
);

-- '2025-26' for an April-start FY.
create function fin.fy_label(p_date date, p_start_month integer) returns text
language sql immutable set search_path = '' as $$
  select case when extract(month from p_date)::int >= p_start_month
    then extract(year from p_date)::int || '-' || lpad(((extract(year from p_date)::int + 1) % 100)::text, 2, '0')
    else (extract(year from p_date)::int - 1) || '-' || lpad((extract(year from p_date)::int % 100)::text, 2, '0')
  end
$$;

-- Returns the monthly period for a date, creating it (open) if needed.
create function fin.ensure_period(p_company uuid, p_date date) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  v_start date := date_trunc('month', p_date)::date;
  v_fy_month integer;
  v_id uuid;
begin
  select fy_start_month into v_fy_month from fin.companies where id = p_company;
  if v_fy_month is null then
    raise exception 'unknown company' using errcode = '23503';
  end if;
  insert into fin.financial_periods (company_id, start_date, end_date, label, fy_label)
  values (p_company, v_start, (v_start + interval '1 month - 1 day')::date,
          to_char(v_start, 'Mon-YYYY'), fin.fy_label(v_start, v_fy_month))
  on conflict (company_id, start_date) do nothing;
  select id into v_id from fin.financial_periods where company_id = p_company and start_date = v_start;
  return v_id;
end $$;

-- Gap-free entry numbers per company and financial year: ART/2025-26/000001
create table fin.doc_counters (
  company_id uuid not null references fin.companies (id),
  fy_label   text not null,
  last_no    integer not null,
  primary key (company_id, fy_label)
);

create function fin.next_entry_no(p_company uuid, p_date date) returns text
language plpgsql security definer set search_path = '' as $$
declare
  v_code text;
  v_fy text;
  v_no integer;
begin
  if pg_trigger_depth() = 0 then
    raise exception '% may only run inside a database trigger', 'next_entry_no' using errcode = '42501';
  end if;
  select code, fin.fy_label(p_date, fy_start_month) into v_code, v_fy
  from fin.companies where id = p_company;
  insert into fin.doc_counters as d (company_id, fy_label, last_no)
  values (p_company, v_fy, 1)
  on conflict (company_id, fy_label) do update set last_no = d.last_no + 1
  returning last_no into v_no;
  return v_code || '/' || v_fy || '/' || lpad(v_no::text, 6, '0');
end $$;

-- ---------------------------------------------------------------------------
-- Journal entries and lines
-- ---------------------------------------------------------------------------
create table fin.journal_entries (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null references fin.companies (id),
  entry_no          text,
  entry_date        date not null check (entry_date >= date '2000-01-01'),
  period_id         uuid,
  site_id           uuid,
  party_id          uuid,
  entry_type        fin.entry_type not null,
  description       text not null check (length(trim(description)) between 1 and 500),
  reference_no      text check (reference_no is null or length(trim(reference_no)) between 1 and 100),
  payment_method    fin.payment_method,
  notes             text check (notes is null or length(notes) <= 2000),
  status            fin.entry_status not null default 'draft',
  reverses_entry_id uuid unique,
  idempotency_key   text check (idempotency_key is null or length(idempotency_key) between 8 and 100),
  source            fin.entry_source not null default 'manual',
  import_row_id     uuid,
  created_by        uuid not null,
  created_at        timestamptz not null default now(),
  submitted_at      timestamptz,
  approved_by       uuid,
  approved_at       timestamptz,
  posted_at         timestamptz,
  updated_at        timestamptz not null default now(),
  version           integer not null default 1,
  unique (company_id, id),
  unique (company_id, entry_no),
  unique (company_id, idempotency_key),
  foreign key (company_id, period_id) references fin.financial_periods (company_id, id),
  foreign key (company_id, site_id) references fin.sites (company_id, id),
  foreign key (company_id, party_id) references fin.parties (company_id, id),
  foreign key (company_id, reverses_entry_id) references fin.journal_entries (company_id, id),
  check ((entry_type = 'reversal') = (reverses_entry_id is not null))
);
create index ix_entries_company_date on fin.journal_entries (company_id, entry_date desc);
create index ix_entries_company_status on fin.journal_entries (company_id, status);
create index ix_entries_party on fin.journal_entries (company_id, party_id);
create index ix_entries_reference on fin.journal_entries (company_id, lower(reference_no));
-- The same receipt / payment reference cannot be recorded twice (reversed ones excepted).
create unique index ux_entries_receipt_ref on fin.journal_entries
  (company_id, entry_type, payment_method, lower(trim(reference_no)))
  where entry_type in ('receipt', 'payment') and status <> 'reversed' and reference_no is not null;

create table fin.journal_lines (
  id                uuid primary key default gen_random_uuid(),
  entry_id          uuid not null,
  company_id        uuid not null,
  line_no           smallint not null check (line_no > 0),
  account_id        uuid not null,
  party_id          uuid,
  debit             numeric(14, 2) not null default 0 check (debit >= 0),
  credit            numeric(14, 2) not null default 0 check (credit >= 0),
  memo              text check (memo is null or length(memo) <= 500),
  reconciliation_id uuid,
  reconciled_at     timestamptz,
  created_at        timestamptz not null default now(),
  check ((debit > 0) <> (credit > 0)),
  unique (entry_id, line_no),
  foreign key (company_id, entry_id) references fin.journal_entries (company_id, id) on delete cascade,
  foreign key (company_id, account_id) references fin.accounts (company_id, id),
  foreign key (company_id, party_id) references fin.parties (company_id, id)
);
create index ix_lines_account on fin.journal_lines (company_id, account_id);
create index ix_lines_entry on fin.journal_lines (entry_id);

-- ---------------------------------------------------------------------------
-- Approval requests (needed by posting rules below)
-- ---------------------------------------------------------------------------
create type fin.approval_action as enum
  ('reverse_entry', 'opening_balance', 'post_in_closed_period', 'reopen_period');
create type fin.approval_status as enum ('pending', 'approved', 'rejected', 'cancelled', 'used');

create table fin.approval_requests (
  id            uuid primary key default gen_random_uuid(),
  company_id    uuid not null references fin.companies (id),
  action        fin.approval_action not null,
  target_id     uuid not null,
  reason        text not null check (length(trim(reason)) between 5 and 1000),
  payload       jsonb,
  status        fin.approval_status not null default 'pending',
  requested_by  uuid not null,
  requested_at  timestamptz not null default now(),
  decided_by    uuid,
  decided_at    timestamptz,
  decision_note text check (decision_note is null or length(decision_note) <= 1000),
  used_at       timestamptz,
  updated_at    timestamptz not null default now(),
  version       integer not null default 1,
  unique (company_id, id)
);
create unique index ux_approval_one_open on fin.approval_requests (company_id, action, target_id)
  where status in ('pending', 'approved');
create index ix_approval_company_status on fin.approval_requests (company_id, status);

-- Consumes an approved request; raises if none exists. Used by posting rules.
create function fin.consume_approval(p_company uuid, p_action fin.approval_action, p_target uuid)
returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_id uuid;
begin
  if pg_trigger_depth() = 0 then
    raise exception '% may only run inside a database trigger', 'consume_approval' using errcode = '42501';
  end if;
  select id into v_id from fin.approval_requests
  where company_id = p_company and action = p_action and target_id = p_target and status = 'approved'
  for update;
  if v_id is null then
    raise exception 'an approved % request is required', p_action using errcode = '42501';
  end if;
  update fin.approval_requests set status = 'used', used_at = now() where id = v_id;
end $$;

create function fin.tg_approval_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    new.requested_by := fin.uid();
    if new.requested_by is null then
      raise exception 'not authenticated' using errcode = '42501';
    end if;
    if new.status <> 'pending' then
      raise exception 'new requests must be pending' using errcode = 'P0001';
    end if;
    new.decided_by := null; new.decided_at := null; new.used_at := null;
    return new;
  end if;

  if (new.company_id, new.action, new.target_id, new.requested_by, new.reason, new.requested_at)
     is distinct from (old.company_id, old.action, old.target_id, old.requested_by, old.reason, old.requested_at) then
    raise exception 'approval request details cannot change' using errcode = 'P0001';
  end if;

  if old.status = 'pending' and new.status in ('approved', 'rejected') then
    if not fin.has_role(new.company_id, 'company_admin') then
      raise exception 'only a company admin or super admin can decide approvals' using errcode = '42501';
    end if;
    -- Four-eyes rule. A super admin may self-approve only with a written note (audited),
    -- so a one-owner business is not locked out.
    if new.requested_by = fin.uid()
       and not (fin.is_super_admin() and length(trim(coalesce(new.decision_note, ''))) >= 5) then
      raise exception 'you cannot approve or reject your own request' using errcode = '42501';
    end if;
    new.decided_by := fin.uid();
    new.decided_at := now();
  elsif old.status = 'pending' and new.status = 'cancelled' then
    if new.requested_by <> fin.uid() and not fin.has_role(new.company_id, 'company_admin') then
      raise exception 'only the requester or an admin can cancel' using errcode = '42501';
    end if;
  elsif old.status = 'approved' and new.status = 'used' then
    null; -- set by fin.consume_approval
  elsif new.status is distinct from old.status then
    raise exception 'invalid approval status change % -> %', old.status, new.status using errcode = 'P0001';
  end if;
  return new;
end $$;
create trigger tg_guard before insert or update on fin.approval_requests
  for each row execute function fin.tg_approval_guard();
create trigger tg_touch before update on fin.approval_requests for each row execute function fin.tg_touch();

-- ---------------------------------------------------------------------------
-- Entry rules
-- ---------------------------------------------------------------------------
-- Number of (account, party) pairs where a reversal does not exactly mirror the original.
create function fin.reversal_mismatches(p_original uuid, p_reversal uuid) returns integer
language sql stable security definer set search_path = '' as $$
  with o as (
    select account_id, party_id, sum(debit - credit) as net
    from fin.journal_lines where entry_id = p_original group by 1, 2
  ), r as (
    select account_id, party_id, sum(credit - debit) as net
    from fin.journal_lines where entry_id = p_reversal group by 1, 2
  )
  select count(*)::integer from o full join r
    on o.account_id = r.account_id and o.party_id is not distinct from r.party_id
  where o.net is distinct from r.net
$$;

create function fin.validate_posting(p_entry fin.journal_entries) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_lines integer;
  v_debit numeric(14, 2);
  v_credit numeric(14, 2);
  v_cash_lines integer;
  v_noncash_lines integer;
  v_period_status fin.period_status;
  v_orig fin.journal_entries;
begin
  if pg_trigger_depth() = 0 then
    raise exception '% may only run inside a database trigger', 'validate_posting' using errcode = '42501';
  end if;
  -- Role: posting = approving. Openings/adjustments need a company admin.
  if p_entry.entry_type in ('opening', 'adjustment') then
    if not fin.has_role(p_entry.company_id, 'company_admin') then
      raise exception 'only a company admin can post % entries', p_entry.entry_type using errcode = '42501';
    end if;
  elsif not fin.has_role(p_entry.company_id, 'accountant') then
    raise exception 'only an accountant or admin can post entries' using errcode = '42501';
  end if;

  select count(*), coalesce(sum(debit), 0), coalesce(sum(credit), 0),
         count(*) filter (where a.subtype in ('cash', 'bank')),
         count(*) filter (where a.subtype not in ('cash', 'bank'))
  into v_lines, v_debit, v_credit, v_cash_lines, v_noncash_lines
  from fin.journal_lines l join fin.accounts a on a.id = l.account_id
  where l.entry_id = p_entry.id;

  if v_lines < 2 then
    raise exception 'an entry needs at least two lines' using errcode = 'P0001';
  end if;
  if v_debit <> v_credit or v_debit <= 0 then
    raise exception 'entry is not balanced (debit % / credit %)', v_debit, v_credit using errcode = 'P0001';
  end if;

  if p_entry.entry_type in ('receipt', 'payment', 'expense') then
    if p_entry.payment_method is null then
      raise exception 'payment method is required' using errcode = 'P0001';
    end if;
    if v_cash_lines = 0 then
      raise exception '% must use a cash or bank account', p_entry.entry_type using errcode = 'P0001';
    end if;
  elsif p_entry.entry_type = 'transfer' then
    if v_noncash_lines > 0 then
      raise exception 'a transfer may only move money between cash/bank accounts' using errcode = 'P0001';
    end if;
  elsif p_entry.entry_type in ('bill_sale', 'bill_purchase') and v_cash_lines > 0 then
    raise exception 'a bill does not move cash; record the payment separately' using errcode = 'P0001';
  end if;

  -- Opening balances are sensitive: after the first one, each needs approval.
  if p_entry.entry_type = 'opening' and exists (
       select 1 from fin.journal_entries e
       where e.company_id = p_entry.company_id and e.entry_type = 'opening'
         and e.status = 'posted' and e.id <> p_entry.id) then
    perform fin.consume_approval(p_entry.company_id, 'opening_balance', p_entry.id);
  end if;

  select status into v_period_status from fin.financial_periods where id = p_entry.period_id;
  if v_period_status = 'closed' then
    perform fin.consume_approval(p_entry.company_id, 'post_in_closed_period', p_entry.id);
  end if;

  if p_entry.entry_type = 'reversal' then
    select * into v_orig from fin.journal_entries where id = p_entry.reverses_entry_id for update;
    if v_orig.status <> 'posted' or v_orig.entry_type = 'reversal' then
      raise exception 'only a posted, non-reversal entry can be reversed' using errcode = 'P0001';
    end if;
    if fin.reversal_mismatches(v_orig.id, p_entry.id) > 0 then
      raise exception 'a reversal must exactly mirror the original entry' using errcode = 'P0001';
    end if;
    perform fin.consume_approval(p_entry.company_id, 'reverse_entry', v_orig.id);
  end if;
end $$;

create function fin.tg_entries_before() returns trigger
language plpgsql set search_path = '' as $$
declare
  v_uid uuid := fin.uid();
begin
  if tg_op = 'INSERT' then
    if v_uid is null and not fin.is_trusted_console() then
      raise exception 'not authenticated' using errcode = '42501';
    end if;
    new.created_by := coalesce(v_uid, new.created_by);
    if new.status not in ('draft', 'pending_approval') then
      raise exception 'entries must be created as draft; post them afterwards' using errcode = 'P0001';
    end if;
    new.entry_no := null; new.approved_by := null; new.approved_at := null; new.posted_at := null;
    new.submitted_at := case when new.status = 'pending_approval' then now() end;
    new.period_id := fin.ensure_period(new.company_id, new.entry_date);
    return new;
  end if;

  if tg_op = 'DELETE' then
    if old.status not in ('draft', 'pending_approval') then
      raise exception 'posted entries cannot be deleted; reverse them instead' using errcode = '42501';
    end if;
    return old;
  end if;

  -- UPDATE
  if old.status = 'reversed' then
    raise exception 'a reversed entry cannot be changed' using errcode = '42501';
  end if;

  if old.status = 'posted' then
    if new.status = 'reversed'
       and (to_jsonb(new) - array['status', 'updated_at', 'version'])
         = (to_jsonb(old) - array['status', 'updated_at', 'version'])
       and exists (select 1 from fin.journal_entries r
                   where r.reverses_entry_id = old.id and r.status = 'posted') then
      return new;
    end if;
    raise exception 'posted entries are immutable; create a reversal instead' using errcode = '42501';
  end if;

  -- draft / pending_approval
  if (new.company_id, new.created_by, new.created_at, new.source, new.import_row_id, new.entry_type)
     is distinct from (old.company_id, old.created_by, old.created_at, old.source, old.import_row_id, old.entry_type) then
    raise exception 'company, type, creator and source of an entry cannot change' using errcode = 'P0001';
  end if;
  if new.entry_date is distinct from old.entry_date then
    new.period_id := fin.ensure_period(new.company_id, new.entry_date);
  else
    new.period_id := old.period_id;
  end if;
  new.entry_no := old.entry_no; new.approved_by := old.approved_by;
  new.approved_at := old.approved_at; new.posted_at := old.posted_at;

  if new.status = 'pending_approval' and old.status = 'draft' then
    new.submitted_at := now();
  elsif new.status = 'draft' and old.status = 'pending_approval' then
    new.submitted_at := null;
  elsif new.status = 'posted' then
    perform fin.validate_posting(new);
    new.entry_no := fin.next_entry_no(new.company_id, new.entry_date);
    new.approved_by := v_uid;
    new.approved_at := now();
    new.posted_at := now();
  elsif new.status = 'reversed' then
    raise exception 'only posted entries can be reversed' using errcode = 'P0001';
  end if;
  return new;
end $$;

create trigger tg_before before insert or update or delete on fin.journal_entries
  for each row execute function fin.tg_entries_before();
create trigger tg_touch before update on fin.journal_entries for each row execute function fin.tg_touch();

-- When a reversal is posted, mark the original as reversed.
create function fin.tg_entries_after() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.status = 'posted' and old.status <> 'posted' and new.entry_type = 'reversal' then
    update fin.journal_entries set status = 'reversed' where id = new.reverses_entry_id;
  end if;
  return null;
end $$;
create trigger tg_after after update on fin.journal_entries
  for each row execute function fin.tg_entries_after();

-- Lines are editable only while their entry is draft/pending. On posted entries only
-- the reconciliation fields may change.
create function fin.tg_lines_guard() returns trigger
language plpgsql set search_path = '' as $$
declare
  v_status fin.entry_status;
  v_entry uuid := case when tg_op = 'DELETE' then old.entry_id else new.entry_id end;
begin
  select status into v_status from fin.journal_entries where id = v_entry;
  if tg_op = 'DELETE' then
    if v_status is not null and v_status not in ('draft', 'pending_approval') then
      raise exception 'lines of a posted entry cannot be deleted' using errcode = '42501';
    end if;
    return old;
  end if;
  if tg_op = 'UPDATE' and (new.entry_id, new.company_id) is distinct from (old.entry_id, old.company_id) then
    raise exception 'a line cannot move to another entry' using errcode = 'P0001';
  end if;
  if v_status in ('draft', 'pending_approval') then
    if tg_op = 'INSERT' and not exists (
         select 1 from fin.accounts a where a.id = new.account_id and a.is_active) then
      raise exception 'account is inactive' using errcode = 'P0001';
    end if;
    return new;
  end if;
  if tg_op = 'UPDATE'
     and (to_jsonb(new) - array['reconciliation_id', 'reconciled_at'])
       = (to_jsonb(old) - array['reconciliation_id', 'reconciled_at']) then
    return new;
  end if;
  raise exception 'lines of a posted entry are immutable' using errcode = '42501';
end $$;
create trigger tg_guard before insert or update or delete on fin.journal_lines
  for each row execute function fin.tg_lines_guard();

-- Period close/reopen rules.
create function fin.tg_periods_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if (new.company_id, new.start_date, new.end_date) is distinct from (old.company_id, old.start_date, old.end_date) then
    raise exception 'period dates cannot change' using errcode = 'P0001';
  end if;
  if new.status is distinct from old.status then
    if not fin.has_role(new.company_id, 'company_admin') then
      raise exception 'only a company admin can open or close periods' using errcode = '42501';
    end if;
    if new.status = 'open' then
      perform fin.consume_approval(new.company_id, 'reopen_period', new.id);
      new.closed_by := null; new.closed_at := null;
    else
      if exists (select 1 from fin.journal_entries e
                 where e.period_id = new.id and e.status in ('draft', 'pending_approval')) then
        raise exception 'period has unposted entries' using errcode = 'P0001';
      end if;
      new.closed_by := fin.uid(); new.closed_at := now();
    end if;
  end if;
  return new;
end $$;
create trigger tg_guard before update on fin.financial_periods
  for each row execute function fin.tg_periods_guard();

-- Account type of a used account cannot change (would rewrite history).
create function fin.tg_accounts_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if (new.company_id, new.type, new.subtype) is distinct from (old.company_id, old.type, old.subtype)
     and exists (select 1 from fin.journal_lines l where l.account_id = old.id) then
    raise exception 'the type of an account that has entries cannot change' using errcode = 'P0001';
  end if;
  if old.is_system and new.is_active is distinct from old.is_active then
    raise exception 'system accounts cannot be deactivated' using errcode = 'P0001';
  end if;
  return new;
end $$;
create trigger tg_guard before update on fin.accounts for each row execute function fin.tg_accounts_guard();

create trigger tg_touch before update on fin.accounts for each row execute function fin.tg_touch();
create trigger tg_touch before update on fin.parties for each row execute function fin.tg_touch();
create trigger tg_touch before update on fin.financial_periods for each row execute function fin.tg_touch();

create trigger tg_audit after insert or update or delete on fin.accounts for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.parties for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.financial_periods for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.journal_entries for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.journal_lines for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.approval_requests for each row execute function fin.tg_audit();

-- Default chart of accounts, created automatically for every new company.
create function fin.tg_seed_chart_of_accounts() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  p_company uuid := new.id;
begin
  insert into fin.accounts (company_id, code, name, type, subtype, is_system) values
    (p_company, 'CASH',     'Cash in Hand',              'asset',     'cash',             true),
    (p_company, 'AR',       'Accounts Receivable',       'asset',     'receivable',       true),
    (p_company, 'AP',       'Accounts Payable',          'liability', 'payable',          true),
    (p_company, 'ADV',      'Customer Advances',         'liability', 'customer_advance', true),
    (p_company, 'OBE',      'Opening Balance Equity',    'equity',    'opening_equity',   true),
    (p_company, 'INC-SALE', 'Sales / Service Income',    'income',    'other',            true),
    (p_company, 'INC-OTH',  'Other Income',              'income',    'other',            false),
    (p_company, 'EXP-GDN',  'Godown Bill',               'expense',   'other',            false),
    (p_company, 'EXP-DSL',  'Diesel',                    'expense',   'other',            false),
    (p_company, 'EXP-EMP',  'Employee Payment',          'expense',   'other',            false),
    (p_company, 'EXP-WRK',  'Worker Payment',            'expense',   'other',            false),
    (p_company, 'EXP-OTH',  'Other Expenses / Charges',  'expense',   'other',            false)
  on conflict (company_id, code) do nothing;
  return null;
end $$;
create trigger tg_seed_accounts after insert on fin.companies
  for each row execute function fin.tg_seed_chart_of_accounts();
