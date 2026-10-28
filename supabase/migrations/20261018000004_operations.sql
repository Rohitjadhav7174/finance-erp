-- 0004 — Follow-ups, attachments, reconciliations, Excel import staging, backup runs.

create type fin.followup_status as enum ('open', 'done', 'cancelled');

create table fin.follow_ups (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references fin.companies (id),
  bill_id     uuid,
  entry_id    uuid,
  assigned_to uuid references fin.profiles (user_id),
  due_date    date not null,
  note        text not null check (length(trim(note)) between 1 and 1000),
  status      fin.followup_status not null default 'open',
  created_by  uuid not null default fin.uid(),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  version     integer not null default 1,
  foreign key (company_id, bill_id) references fin.bills (company_id, id),
  foreign key (company_id, entry_id) references fin.journal_entries (company_id, id)
);
create index ix_followups_company_due on fin.follow_ups (company_id, status, due_date);

create type fin.attachment_entity as enum ('entry', 'bill', 'party', 'reconciliation');

create table fin.attachments (
  id           uuid primary key default gen_random_uuid(),
  company_id   uuid not null references fin.companies (id),
  entity       fin.attachment_entity not null,
  entity_id    uuid not null,
  storage_path text not null unique,
  file_name    text not null check (length(file_name) between 1 and 200),
  mime_type    text not null check (mime_type in ('application/pdf', 'image/jpeg', 'image/png')),
  size_bytes   integer not null check (size_bytes between 1 and 5242880),
  sha256       text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  uploaded_by  uuid not null default fin.uid(),
  created_at   timestamptz not null default now()
);
create index ix_attachments_entity on fin.attachments (company_id, entity, entity_id);

create type fin.reconciliation_status as enum ('in_progress', 'completed');

create table fin.reconciliations (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null,
  account_id        uuid not null,
  statement_date    date not null,
  statement_balance numeric(14, 2) not null,
  book_balance      numeric(14, 2),
  difference        numeric(14, 2),
  status            fin.reconciliation_status not null default 'in_progress',
  note              text check (note is null or length(note) <= 1000),
  created_by        uuid not null default fin.uid(),
  completed_by      uuid,
  completed_at      timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  version           integer not null default 1,
  unique (company_id, id),
  foreign key (company_id) references fin.companies (id),
  foreign key (company_id, account_id) references fin.accounts (company_id, id)
);
create unique index ux_reconciliation_open on fin.reconciliations (account_id)
  where status = 'in_progress';

alter table fin.journal_lines
  add constraint fk_lines_reconciliation
  foreign key (company_id, reconciliation_id) references fin.reconciliations (company_id, id);

create type fin.import_status as enum ('previewed', 'confirmed', 'posted', 'discarded');
create type fin.import_decision as enum ('pending', 'import', 'skip', 'duplicate');

create table fin.import_batches (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references fin.companies (id),
  file_name   text not null,
  file_sha256 text not null check (file_sha256 ~ '^[0-9a-f]{64}$'),
  status      fin.import_status not null default 'previewed',
  summary     jsonb not null default '{}'::jsonb,
  uploaded_by uuid not null default fin.uid(),
  confirmed_by uuid,
  confirmed_at timestamptz,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  version     integer not null default 1,
  unique (company_id, id)
);
-- The same file cannot be imported twice into a company (unless the earlier batch was discarded).
create unique index ux_import_file_once on fin.import_batches (company_id, file_sha256)
  where status <> 'discarded';

create table fin.import_rows (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null,
  batch_id   uuid not null,
  sheet      text not null,
  row_number integer not null check (row_number > 0),
  raw        jsonb not null,
  mapped     jsonb,
  issues     jsonb not null default '[]'::jsonb,
  decision   fin.import_decision not null default 'pending',
  created_at timestamptz not null default now(),
  unique (batch_id, sheet, row_number),
  unique (company_id, id),
  foreign key (company_id, batch_id) references fin.import_batches (company_id, id) on delete cascade
);

-- The original cells of an imported row are evidence; never rewrite them.
create function fin.tg_import_rows_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.raw is distinct from old.raw or new.sheet is distinct from old.sheet
     or new.row_number is distinct from old.row_number then
    raise exception 'original import data cannot be changed' using errcode = '42501';
  end if;
  return new;
end $$;
create trigger tg_guard before update on fin.import_rows
  for each row execute function fin.tg_import_rows_guard();

alter table fin.journal_entries
  add constraint fk_entries_import_row foreign key (company_id, import_row_id)
  references fin.import_rows (company_id, id);
alter table fin.bills
  add constraint fk_bills_import_row foreign key (company_id, import_row_id)
  references fin.import_rows (company_id, id);

create type fin.backup_status as enum ('running', 'succeeded', 'failed', 'verified');

create table fin.backup_runs (
  id             uuid primary key default gen_random_uuid(),
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  status         fin.backup_status not null default 'running',
  object_key     text,
  size_bytes     bigint,
  sha256         text,
  row_counts     jsonb,
  control_totals jsonb,
  verified_at    timestamptz,
  error          text
);

create table fin.system_settings (
  key        text primary key check (key ~ '^[a-z_.]{3,60}$'),
  value      jsonb not null,
  updated_by uuid,
  updated_at timestamptz not null default now()
);
insert into fin.system_settings (key, value) values
  ('backup.retention_days', '90'),
  ('backup.max_age_hours', '26');

create trigger tg_touch before update on fin.follow_ups for each row execute function fin.tg_touch();
create trigger tg_touch before update on fin.reconciliations for each row execute function fin.tg_touch();
create trigger tg_touch before update on fin.import_batches for each row execute function fin.tg_touch();

create trigger tg_audit after insert or update or delete on fin.follow_ups for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.attachments for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.reconciliations for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.import_batches for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.backup_runs for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.system_settings for each row execute function fin.tg_audit();
