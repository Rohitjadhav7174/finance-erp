-- Gives the login "Ramdas" full access to every company (super admin, like the owner).
-- First create the login itself in Supabase → Authentication → Users → Add user → Create new user:
--     Email:     ramdas@login.local      (internal address; Ramdas types just "Ramdas" on the sign-in page)
--     Password:  the password you chose  (typed only into Supabase, never stored in this file)
--     Tick "Auto Confirm User".
-- Then run this file once in Supabase → SQL Editor.

do $$
declare
  v_user uuid;
begin
  select id into v_user from auth.users where lower(email) = 'ramdas@login.local';
  if v_user is null then
    raise exception 'Create the user ramdas@login.local in Authentication → Users first';
  end if;
  insert into fin.profiles (user_id, full_name, email, is_super_admin, can_view_consolidated)
  values (v_user, 'Ramdas', 'ramdas@login.local', true, true)
  on conflict (user_id) do update set is_super_admin = true, can_view_consolidated = true, is_active = true;
end $$;

select full_name, email, is_super_admin from fin.profiles where email = 'ramdas@login.local';
