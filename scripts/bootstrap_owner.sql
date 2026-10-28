-- One-time setup of the first company owner (super admin) and the two companies.
-- Run ONCE in the Supabase SQL editor AFTER:
--   1. migrations are applied, and
--   2. the owner has been invited in Supabase → Authentication → Users → "Invite user" (their email),
-- Replace the three values marked >>> … <<<. Real company details only — no SAMPLE data here.

do $$
declare
  v_owner uuid;
begin
  select id into v_owner from auth.users where lower(email) = lower('>>> owner@email <<<');
  if v_owner is null then
    raise exception 'Invite the owner in Authentication → Users first';
  end if;
  insert into fin.profiles (user_id, full_name, email, is_super_admin, can_view_consolidated)
  values (v_owner, '>>> Owner full name <<<', lower('>>> owner@email <<<'), true, true)
  on conflict (user_id) do update set is_super_admin = true, can_view_consolidated = true, is_active = true;

  -- The default chart of accounts is created automatically for each company.
  insert into fin.companies (code, name, address, theme_color) values
    ('JGT', 'Jay Ganesh Transport', null, '#e8590c'),
    ('ART', 'A R Trading Company', 'Sindhudurg', '#1971c2')
  on conflict (code) do nothing;

  insert into fin.sites (company_id, name)
  select id, s from fin.companies, unnest(array['Sindhudurg', 'Ratnagiri']) s where code = 'ART'
  on conflict do nothing;
end $$;

-- Check:
select c.code, c.name, (select count(*) from fin.accounts a where a.company_id = c.id) as accounts from fin.companies c;
