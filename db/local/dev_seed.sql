-- LOCAL DEVELOPMENT ONLY — SAMPLE DATA, NOT REAL COMPANY RECORDS.
-- Run after scripts/local_db.sh reset. Creates two sample companies and a few
-- sample users with fixed ids so dev tokens can be generated for them.

insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-000000000001', 'owner@example.com'),
  ('00000000-0000-4000-8000-000000000002', 'accounts.art@example.com'),
  ('00000000-0000-4000-8000-000000000003', 'entry.jgt@example.com');

insert into fin.profiles (user_id, full_name, email, phone, is_super_admin, can_view_consolidated) values
  ('00000000-0000-4000-8000-000000000001', 'Sample Owner', 'owner@example.com', null, true, true),
  ('00000000-0000-4000-8000-000000000002', 'Sample Accountant', 'accounts.art@example.com', '9800000002', false, false),
  ('00000000-0000-4000-8000-000000000003', 'Sample Operator', 'entry.jgt@example.com', '9800000003', false, false);

insert into fin.companies (id, code, name, address, theme_color) values
  ('10000000-0000-4000-8000-000000000001', 'JGT', 'SAMPLE Jay Ganesh Transport', 'Sample address', '#e8590c'),
  ('10000000-0000-4000-8000-000000000002', 'ART', 'SAMPLE AR Trading', 'Sindhudurg', '#1971c2');

insert into fin.sites (company_id, name) values
  ('10000000-0000-4000-8000-000000000002', 'Sindhudurg'),
  ('10000000-0000-4000-8000-000000000002', 'Ratnagiri');

insert into fin.company_memberships (user_id, company_id, role) values
  ('00000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000002', 'accountant'),
  ('00000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000001', 'data_entry');
