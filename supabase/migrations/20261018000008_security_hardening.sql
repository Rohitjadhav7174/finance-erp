-- 0008 — Phase 6 security review fixes.
--
-- 1. fin.ensure_period() is SECURITY DEFINER and was callable directly by the API role,
--    which would let a user of one company create (empty) periods in another company.
--    It now runs only inside database triggers (entry creation), like next_entry_no.
-- 2. fin.reversal_mismatches() was SECURITY DEFINER, so a direct call could compare the
--    lines of another company's entries. It is now SECURITY INVOKER (RLS applies); the
--    posting check still works because it is called from validate_posting (definer).

create or replace function fin.ensure_period(p_company uuid, p_date date) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  v_start date := date_trunc('month', p_date)::date;
  v_fy_month integer;
  v_id uuid;
begin
  if pg_trigger_depth() = 0 then
    raise exception 'ensure_period may only run inside a database trigger' using errcode = '42501';
  end if;
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

create or replace function fin.reversal_mismatches(p_original uuid, p_reversal uuid) returns integer
language sql stable security invoker set search_path = '' as $$
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
