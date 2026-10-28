-- LOCAL TESTING ONLY. Never run against Supabase.
-- Recreates the minimal pieces of Supabase that our migrations rely on:
-- the auth schema, auth.users, auth.uid(), and the anon/authenticated/service_role roles.
-- auth.uid() matches Supabase's implementation: it reads the JWT 'sub' claim
-- from the request.jwt.claims setting.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;

create schema if not exists auth;
grant usage on schema auth to anon, authenticated, service_role;

create table if not exists auth.users (
  id uuid primary key default gen_random_uuid(),
  email text unique,
  created_at timestamptz not null default now()
);

create or replace function auth.uid() returns uuid
language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  )::uuid
$$;
grant execute on function auth.uid() to public;

-- Supabase grants anon/authenticated broad default privileges on public; mimic that so
-- tests prove our fin schema is unreachable even where defaults are permissive.
grant usage on schema public to anon, authenticated;
