-- 0003 — Bills, installment schedules, and allocations of receipts/payments to bills.
--
-- Rules:
--   * A bill is recorded independently of payments. Posting its journal entry
--     (bill_sale / bill_purchase) recognises the receivable/payable once.
--   * Receipts are allocated to receivable bills, payments to payable bills.
--     A receipt allocated to a bill must credit Accounts Receivable, so
--     installments are never counted as additional income.
--   * Total allocations can never exceed the bill amount (row lock prevents races).
--   * Bill amount, party and number are frozen once posted.
--   * Bill status (paid/partial/overdue) is always computed, never typed in.

create type fin.bill_direction as enum ('receivable', 'payable');
create type fin.bill_status as enum ('draft', 'posted', 'cancelled');

create table fin.bills (
  id               uuid primary key default gen_random_uuid(),
  company_id       uuid not null references fin.companies (id),
  bill_no          text not null check (length(trim(bill_no)) between 1 and 100),
  direction        fin.bill_direction not null,
  party_id         uuid not null,
  bill_date        date not null check (bill_date >= date '2000-01-01'),
  period_from      date,
  period_to        date,
  due_date         date,
  site_id          uuid,
  amount           numeric(14, 2) not null check (amount > 0),
  description      text not null check (length(trim(description)) between 1 and 500),
  notes            text check (notes is null or length(notes) <= 2000),
  journal_entry_id uuid unique,
  status           fin.bill_status not null default 'draft',
  source           fin.entry_source not null default 'manual',
  import_row_id    uuid,
  created_by       uuid not null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  version          integer not null default 1,
  unique (company_id, id),
  foreign key (company_id, party_id) references fin.parties (company_id, id),
  foreign key (company_id, site_id) references fin.sites (company_id, id),
  foreign key (company_id, journal_entry_id) references fin.journal_entries (company_id, id),
  check (period_from is null or period_to is null or period_to >= period_from),
  check (due_date is null or due_date >= bill_date)
);
create unique index ux_bills_no on fin.bills (company_id, direction, lower(trim(bill_no)))
  where status <> 'cancelled';
create index ix_bills_company_due on fin.bills (company_id, due_date);
create index ix_bills_party on fin.bills (company_id, party_id);

create table fin.installment_schedule (
  id              uuid primary key default gen_random_uuid(),
  company_id      uuid not null,
  bill_id         uuid not null,
  seq             smallint not null check (seq > 0),
  due_date        date not null,
  expected_amount numeric(14, 2) not null check (expected_amount > 0),
  note            text check (note is null or length(note) <= 500),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  version         integer not null default 1,
  unique (bill_id, seq),
  foreign key (company_id, bill_id) references fin.bills (company_id, id) on delete cascade
);
create index ix_installments_due on fin.installment_schedule (company_id, due_date);

create table fin.bill_allocations (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null,
  bill_id    uuid not null,
  entry_id   uuid not null,
  amount     numeric(14, 2) not null check (amount > 0),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  unique (bill_id, entry_id),
  foreign key (company_id, bill_id) references fin.bills (company_id, id),
  foreign key (company_id, entry_id) references fin.journal_entries (company_id, id) on delete cascade
);
create index ix_allocations_entry on fin.bill_allocations (entry_id);

-- ---------------------------------------------------------------------------
-- Bill guard
-- ---------------------------------------------------------------------------
create function fin.tg_bills_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    new.created_by := coalesce(fin.uid(), case when fin.is_trusted_console() then new.created_by end);
    if new.created_by is null then
      raise exception 'not authenticated' using errcode = '42501';
    end if;
    if new.status <> 'draft' then
      raise exception 'bills are created as draft' using errcode = 'P0001';
    end if;
    return new;
  end if;
  if tg_op = 'DELETE' then
    if old.status <> 'draft' then
      raise exception 'posted bills cannot be deleted; cancel by reversing their entry' using errcode = '42501';
    end if;
    return old;
  end if;
  if (new.company_id, new.created_by, new.created_at, new.source, new.import_row_id)
     is distinct from (old.company_id, old.created_by, old.created_at, old.source, old.import_row_id) then
    raise exception 'company, creator and source of a bill cannot change' using errcode = 'P0001';
  end if;
  if old.status <> 'draft' then
    -- Only notes, due date and the system-driven status may change after posting.
    if (to_jsonb(new) - array['notes', 'due_date', 'status', 'updated_at', 'version'])
       is distinct from (to_jsonb(old) - array['notes', 'due_date', 'status', 'updated_at', 'version']) then
      raise exception 'a posted bill is frozen; correct it with a reversal and a new bill' using errcode = '42501';
    end if;
  end if;
  if new.status is distinct from old.status then
    if new.status = 'posted' and not exists (
         select 1 from fin.journal_entries e where e.id = new.journal_entry_id and e.status = 'posted') then
      raise exception 'a bill becomes posted only when its journal entry is posted' using errcode = 'P0001';
    end if;
    if new.status = 'cancelled' and old.status = 'posted' and not exists (
         select 1 from fin.journal_entries e where e.id = new.journal_entry_id and e.status = 'reversed') then
      raise exception 'a posted bill is cancelled only by reversing its entry' using errcode = 'P0001';
    end if;
    if new.status = 'draft' then
      raise exception 'a bill cannot return to draft' using errcode = 'P0001';
    end if;
  end if;
  return new;
end $$;
create trigger tg_guard before insert or update or delete on fin.bills
  for each row execute function fin.tg_bills_guard();

-- Keeps bill status in step with its journal entry and validates the bill posting
-- (receivable/payable line for the bill's party equal to the bill amount).
create function fin.tg_entries_sync_bills() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_bill fin.bills;
  v_ok boolean;
  v_alloc numeric(14, 2);
  v_ar_credit numeric(14, 2);
  v_ap_debit numeric(14, 2);
begin
  if new.status = old.status then
    return null;
  end if;

  select * into v_bill from fin.bills where journal_entry_id = new.id;

  if new.status = 'posted' then
    if v_bill.id is not null then
      if (new.entry_type = 'bill_sale') <> (v_bill.direction = 'receivable')
         or new.entry_type not in ('bill_sale', 'bill_purchase') then
        raise exception 'bill entry type does not match bill direction' using errcode = 'P0001';
      end if;
      select coalesce(sum(case when v_bill.direction = 'receivable' then l.debit - l.credit
                               else l.credit - l.debit end), 0) = v_bill.amount
      into v_ok
      from fin.journal_lines l join fin.accounts a on a.id = l.account_id
      where l.entry_id = new.id
        and a.subtype = case when v_bill.direction = 'receivable' then 'receivable'::fin.account_subtype
                             else 'payable'::fin.account_subtype end
        and l.party_id = v_bill.party_id;
      if not v_ok then
        raise exception 'bill entry must % the party''s % account by exactly the bill amount',
          case when v_bill.direction = 'receivable' then 'debit' else 'credit' end,
          case when v_bill.direction = 'receivable' then 'receivable' else 'payable' end
          using errcode = 'P0001';
      end if;
      update fin.bills set status = 'posted' where id = v_bill.id;
    end if;

    -- Allocations carried by this receipt/payment must be backed by AR credit / AP debit.
    select coalesce(sum(amount), 0) into v_alloc from fin.bill_allocations where entry_id = new.id;
    if v_alloc > 0 then
      select coalesce(sum(l.credit - l.debit) filter (where a.subtype = 'receivable'), 0),
             coalesce(sum(l.debit - l.credit) filter (where a.subtype = 'payable'), 0)
      into v_ar_credit, v_ap_debit
      from fin.journal_lines l join fin.accounts a on a.id = l.account_id
      where l.entry_id = new.id;
      if new.entry_type = 'receipt' and v_alloc > v_ar_credit then
        raise exception 'a receipt allocated to bills must credit Accounts Receivable by at least the allocated amount'
          using errcode = 'P0001';
      elsif new.entry_type = 'payment' and v_alloc > v_ap_debit then
        raise exception 'a payment allocated to bills must debit Accounts Payable by at least the allocated amount'
          using errcode = 'P0001';
      end if;
    end if;
  elsif new.status = 'reversed' and v_bill.id is not null then
    if exists (select 1 from fin.bill_allocations ba join fin.journal_entries e on e.id = ba.entry_id
               where ba.bill_id = v_bill.id and e.status = 'posted') then
      raise exception 'reverse the payments allocated to this bill first' using errcode = 'P0001';
    end if;
    update fin.bills set status = 'cancelled' where id = v_bill.id;
  end if;
  return null;
end $$;
create trigger tg_sync_bills after update on fin.journal_entries
  for each row execute function fin.tg_entries_sync_bills();

-- ---------------------------------------------------------------------------
-- Allocation guard (locks the bill row to serialise concurrent allocations)
-- ---------------------------------------------------------------------------
create function fin.tg_allocations_guard() returns trigger
language plpgsql set search_path = '' as $$
declare
  v_bill fin.bills;
  v_entry fin.journal_entries;
  v_total numeric(14, 2);
begin
  if tg_op = 'DELETE' then
    select * into v_entry from fin.journal_entries where id = old.entry_id;
    if v_entry.status in ('posted', 'reversed') then
      raise exception 'allocations of a posted entry cannot be removed' using errcode = '42501';
    end if;
    return old;
  end if;
  if tg_op = 'UPDATE' then
    raise exception 'allocations cannot be edited; delete the draft allocation and add a new one'
      using errcode = 'P0001';
  end if;

  new.created_by := coalesce(fin.uid(), case when fin.is_trusted_console() then new.created_by end);
  if new.created_by is null then
    raise exception 'not authenticated' using errcode = '42501';
  end if;

  select * into v_bill from fin.bills where id = new.bill_id for update;
  select * into v_entry from fin.journal_entries where id = new.entry_id;

  if v_bill.status <> 'posted' then
    raise exception 'payments can only be allocated to a posted bill' using errcode = 'P0001';
  end if;
  if v_entry.status not in ('draft', 'pending_approval') then
    raise exception 'allocate while the receipt/payment is still a draft' using errcode = 'P0001';
  end if;
  if (v_bill.direction = 'receivable' and v_entry.entry_type <> 'receipt')
     or (v_bill.direction = 'payable' and v_entry.entry_type <> 'payment') then
    raise exception 'receivable bills take receipts; payable bills take payments' using errcode = 'P0001';
  end if;
  if v_entry.party_id is distinct from v_bill.party_id then
    raise exception 'the receipt/payment party must match the bill party' using errcode = 'P0001';
  end if;

  select coalesce(sum(ba.amount), 0) into v_total
  from fin.bill_allocations ba join fin.journal_entries e on e.id = ba.entry_id
  where ba.bill_id = new.bill_id and e.status <> 'reversed';
  if v_total + new.amount > v_bill.amount then
    raise exception 'allocation exceeds the bill outstanding (bill %, already allocated %, new %)',
      v_bill.amount, v_total, new.amount using errcode = 'P0001';
  end if;
  return new;
end $$;
create trigger tg_guard before insert or update or delete on fin.bill_allocations
  for each row execute function fin.tg_allocations_guard();

-- Installment schedule may not exceed the bill amount.
create function fin.tg_installments_guard() returns trigger
language plpgsql set search_path = '' as $$
declare
  v_amount numeric(14, 2);
  v_total numeric(14, 2);
begin
  select amount into v_amount from fin.bills where id = new.bill_id for update;
  select coalesce(sum(expected_amount), 0) into v_total
  from fin.installment_schedule where bill_id = new.bill_id and id <> new.id;
  if v_total + new.expected_amount > v_amount then
    raise exception 'installments (%) exceed the bill amount (%)', v_total + new.expected_amount, v_amount
      using errcode = 'P0001';
  end if;
  return new;
end $$;
create trigger tg_guard before insert or update on fin.installment_schedule
  for each row execute function fin.tg_installments_guard();

create trigger tg_touch before update on fin.bills for each row execute function fin.tg_touch();
create trigger tg_touch before update on fin.installment_schedule for each row execute function fin.tg_touch();
create trigger tg_audit after insert or update or delete on fin.bills for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.installment_schedule for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.bill_allocations for each row execute function fin.tg_audit();

-- ---------------------------------------------------------------------------
-- Computed bill balances (SECURITY INVOKER: callers only see bills RLS allows)
-- ---------------------------------------------------------------------------
create function fin.bill_balances(p_company uuid, p_as_of date default current_date)
returns table (
  bill_id uuid, bill_no text, direction fin.bill_direction, party_id uuid,
  bill_date date, due_date date, amount numeric, paid numeric, outstanding numeric, pay_status text
)
language sql stable set search_path = '' as $$
  select b.id, b.bill_no, b.direction, b.party_id, b.bill_date, b.due_date, b.amount,
         coalesce(p.paid, 0),
         b.amount - coalesce(p.paid, 0),
         case
           when coalesce(p.paid, 0) >= b.amount then 'paid'
           when b.due_date is not null and b.due_date < p_as_of then 'overdue'
           when coalesce(p.paid, 0) > 0 then 'partially_paid'
           else 'pending'
         end
  from fin.bills b
  left join lateral (
    select sum(ba.amount) as paid
    from fin.bill_allocations ba join fin.journal_entries e on e.id = ba.entry_id
    where ba.bill_id = b.id and e.status = 'posted' and e.entry_date <= p_as_of
  ) p on true
  where b.company_id = p_company and b.status = 'posted' and b.bill_date <= p_as_of
$$;
