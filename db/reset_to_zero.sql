-- Start the books again from zero.
--
-- KEEPS: companies, sites, the account list (Cash in Hand, Bank, Godown Bill, Diesel… — names only,
--        no amounts), logins and who can access which company, and system settings.
-- REMOVES: every entry, bill, installment, customer/supplier, import, reconciliation, approval,
--          closed month, entry-number counter, attachment record, backup record and the audit log.
--
-- This cannot be undone. Run it once, in Supabase → SQL Editor (it runs as the database owner).
-- TRUNCATE is used on purpose: posted entries and the audit log refuse row-by-row deletes.
-- The audit log's own truncate lock is switched off only inside this transaction and back on before commit.
-- It fails, and changes nothing, if any table that is kept still points at one being emptied.

begin;

select 'before' as at,
  (select count(*) from fin.journal_entries) as entries,
  (select count(*) from fin.bills) as bills,
  (select count(*) from fin.parties) as parties,
  (select count(*) from fin.companies) as companies,
  (select count(*) from fin.accounts) as accounts;

alter table fin.audit_log disable trigger tg_append_only_truncate;

truncate table
  fin.journal_lines,
  fin.bill_allocations,
  fin.installment_schedule,
  fin.follow_ups,
  fin.bills,
  fin.journal_entries,
  fin.reconciliations,
  fin.import_rows,
  fin.import_batches,
  fin.parties,
  fin.approval_requests,
  fin.attachments,
  fin.financial_periods,
  fin.doc_counters,
  fin.backup_runs,
  fin.security_events,
  fin.audit_log
restart identity;

alter table fin.audit_log enable trigger tg_append_only_truncate;

select 'after' as at,
  (select count(*) from fin.journal_entries) as entries,
  (select count(*) from fin.bills) as bills,
  (select count(*) from fin.parties) as parties,
  (select count(*) from fin.companies) as companies,
  (select count(*) from fin.accounts) as accounts;

commit;
