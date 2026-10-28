-- 0006 — Phase 3 workflow adjustments.
--   * Data-entry operators may manage the installment schedule of their OWN DRAFT bills
--     (previously accountant-only), so a bill and its schedule can be entered together.
--   * Search helpers: trigram-free indexes suitable for the entry/bill search screens.

drop policy installments_insert on fin.installment_schedule;
drop policy installments_update on fin.installment_schedule;
drop policy installments_delete on fin.installment_schedule;

create function fin.can_edit_bill(p_bill uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from fin.bills b
    where b.id = p_bill
      and (fin.has_role(b.company_id, 'accountant')
           or (b.status = 'draft' and fin.has_role(b.company_id, 'data_entry') and b.created_by = fin.uid()))
  )
$$;
grant execute on function fin.can_edit_bill(uuid) to app_api;

create policy installments_insert on fin.installment_schedule for insert to app_api
  with check (fin.can_edit_bill(bill_id));
create policy installments_update on fin.installment_schedule for update to app_api
  using (fin.can_edit_bill(bill_id)) with check (fin.can_edit_bill(bill_id));
create policy installments_delete on fin.installment_schedule for delete to app_api
  using (fin.can_edit_bill(bill_id));

create index ix_entries_description on fin.journal_entries (company_id, lower(description) text_pattern_ops);
create index ix_bills_no_search on fin.bills (company_id, lower(bill_no) text_pattern_ops);
