-- 0001 — Schema, roles, identity, company access, permission helpers, audit log.
--
-- Security model:
--   * All financial tables live in schema `fin`, which is NOT exposed through
--     Supabase's REST API. anon/authenticated get no privileges on it.
--   * The FastAPI backend connects as role `app_api` (not a superuser, no BYPASSRLS).
--     Per transaction it sets request.jwt.claims to the verified user's JWT claims,
--     so fin.uid() returns the real user and every RLS policy applies.
--   * If the backend forgets to set claims, fin.uid() is NULL and every policy
--     denies access (fail closed).
--   * The `app_api` login password is set outside migrations (see docs/deployment).

create schema if not exists fin;
revoke all on schema fin from public;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_api') then
    create role app_api nologin noinherit;
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on schema fin from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on schema fin from authenticated';
  end if;
end $$;

grant usage on schema fin to app_api;
alter default privileges in schema fin revoke all on tables from public;
alter default privileges in schema fin revoke execute on functions from public;

-- Current user id from the verified JWT claims the backend sets per transaction.
-- Same logic as Supabase's auth.uid(), defined here so we depend only on the
-- request.jwt.claims setting. NULL when unset (fail closed).
create function fin.uid() returns uuid
language sql stable set search_path = '' as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'
  )::uuid
$$;
grant execute on function fin.uid() to app_api;

-- ---------------------------------------------------------------------------
-- Types
-- ---------------------------------------------------------------------------
create type fin.app_role as enum ('viewer', 'data_entry', 'accountant', 'company_admin');

-- ---------------------------------------------------------------------------
-- Generic row maintenance: updated_at + optimistic-lock version
-- ---------------------------------------------------------------------------
create function fin.tg_touch() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  new.version := old.version + 1;
  return new;
end $$;

-- ---------------------------------------------------------------------------
-- Companies, sites, profiles, memberships
-- ---------------------------------------------------------------------------
create table fin.companies (
  id             uuid primary key default gen_random_uuid(),
  code           text not null unique check (code ~ '^[A-Z]{2,6}$'),
  name           text not null check (length(trim(name)) between 2 and 200),
  address        text,
  gstin          text check (gstin is null or gstin ~ '^[0-9A-Z]{15}$'),
  bank_details   text,
  theme_color    text not null default '#1c7ed6' check (theme_color ~ '^#[0-9a-fA-F]{6}$'),
  fy_start_month smallint not null default 4 check (fy_start_month between 1 and 12),
  is_active      boolean not null default true,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  version        integer not null default 1
);

create table fin.sites (
  id         uuid primary key default gen_random_uuid(),
  company_id uuid not null references fin.companies (id),
  name       text not null check (length(trim(name)) between 1 and 100),
  is_active  boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version    integer not null default 1,
  unique (company_id, id)
);
create unique index ux_sites_name on fin.sites (company_id, lower(name));

create table fin.profiles (
  user_id               uuid primary key references auth.users (id) on delete restrict,
  full_name             text not null check (length(trim(full_name)) between 1 and 200),
  email                 text not null,
  phone                 text,
  is_active             boolean not null default true,
  is_super_admin        boolean not null default false,
  can_view_consolidated boolean not null default false,
  deactivated_at        timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  version               integer not null default 1
);
create unique index ux_profiles_email on fin.profiles (lower(email));

create table fin.company_memberships (
  user_id    uuid not null references fin.profiles (user_id),
  company_id uuid not null references fin.companies (id),
  role       fin.app_role not null,
  is_active  boolean not null default true,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  version    integer not null default 1,
  primary key (user_id, company_id)
);
create index ix_memberships_company on fin.company_memberships (company_id);

create trigger tg_touch before update on fin.companies for each row execute function fin.tg_touch();
create trigger tg_touch before update on fin.sites for each row execute function fin.tg_touch();
create trigger tg_touch before update on fin.profiles for each row execute function fin.tg_touch();
create trigger tg_touch before update on fin.company_memberships for each row execute function fin.tg_touch();

-- ---------------------------------------------------------------------------
-- Permission helpers (SECURITY DEFINER so RLS policies can consult membership
-- tables without recursive policy evaluation). All are fail-closed on NULL uid.
-- ---------------------------------------------------------------------------
create function fin.role_rank(r fin.app_role) returns integer
language sql immutable set search_path = '' as $$
  select case r
    when 'viewer' then 1
    when 'data_entry' then 2
    when 'accountant' then 3
    when 'company_admin' then 4
  end
$$;

create function fin.is_super_admin() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from fin.profiles p
    where p.user_id = fin.uid() and p.is_active and p.is_super_admin
  )
$$;

create function fin.company_role(p_company uuid) returns fin.app_role
language sql stable security definer set search_path = '' as $$
  select m.role
  from fin.company_memberships m
  join fin.profiles p on p.user_id = m.user_id
  join fin.companies c on c.id = m.company_id
  where m.user_id = fin.uid()
    and m.company_id = p_company
    and m.is_active and p.is_active and c.is_active
$$;

-- True when the current user holds at least p_min in p_company (super admins always).
create function fin.has_role(p_company uuid, p_min fin.app_role) returns boolean
language sql stable security definer set search_path = '' as $$
  select fin.is_super_admin()
      or coalesce(fin.role_rank(fin.company_role(p_company)) >= fin.role_rank(p_min), false)
$$;

grant execute on function fin.role_rank(fin.app_role), fin.is_super_admin(),
  fin.company_role(uuid), fin.has_role(uuid, fin.app_role) to app_api;

-- ---------------------------------------------------------------------------
-- Guard rules for identity tables
-- ---------------------------------------------------------------------------
-- Guards run as the caller (not SECURITY DEFINER) so `current_user` tells the
-- backend (app_api) apart from a database administrator doing the initial
-- bootstrap from the SQL console (no JWT, not app_api).
create function fin.is_trusted_console() returns boolean
language sql stable set search_path = '' as $$
  select fin.uid() is null and current_user <> 'app_api'
$$;

create function fin.tg_profiles_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if fin.is_trusted_console() then
    return new;
  end if;
  if tg_op = 'INSERT' then
    if (new.is_super_admin or new.can_view_consolidated) and not fin.is_super_admin() then
      raise exception 'only a super admin can grant privileges' using errcode = '42501';
    end if;
    return new;
  end if;
  if new.user_id <> old.user_id then
    raise exception 'user_id cannot change' using errcode = 'P0001';
  end if;
  -- Only super admins may change privilege flags or activation.
  if (new.is_super_admin, new.can_view_consolidated, new.is_active)
     is distinct from (old.is_super_admin, old.can_view_consolidated, old.is_active)
     and not fin.is_super_admin() then
    raise exception 'only a super admin can change privileges or activation' using errcode = '42501';
  end if;
  if new.user_id = fin.uid() and old.is_super_admin and not (new.is_super_admin and new.is_active) then
    raise exception 'you cannot remove your own super admin rights' using errcode = 'P0001';
  end if;
  if new.is_active is distinct from old.is_active then
    new.deactivated_at := case when new.is_active then null else now() end;
  end if;
  return new;
end $$;
create trigger tg_guard before insert or update on fin.profiles for each row execute function fin.tg_profiles_guard();

create function fin.tg_memberships_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if fin.is_trusted_console() then
    return new;
  end if;
  if tg_op = 'INSERT' then
    new.created_by := fin.uid();
  end if;
  if tg_op = 'UPDATE' and (new.user_id, new.company_id) <> (old.user_id, old.company_id) then
    raise exception 'membership keys cannot change' using errcode = 'P0001';
  end if;
  if not fin.is_super_admin() then
    -- Company admins manage accountant/data_entry/viewer only, never themselves.
    if new.user_id = fin.uid() then
      raise exception 'you cannot change your own company access' using errcode = '42501';
    end if;
    if new.role = 'company_admin' or (tg_op = 'UPDATE' and old.role = 'company_admin') then
      raise exception 'only a super admin can grant or change company admin access' using errcode = '42501';
    end if;
  end if;
  return new;
end $$;
create trigger tg_guard before insert or update on fin.company_memberships
  for each row execute function fin.tg_memberships_guard();

-- ---------------------------------------------------------------------------
-- Audit log (append-only) and security events
-- ---------------------------------------------------------------------------
create table fin.audit_log (
  id         bigint generated always as identity primary key,
  at         timestamptz not null default now(),
  actor_id   uuid,
  company_id uuid,
  action     text not null,
  table_name text not null,
  record_id  text,
  old_data   jsonb,
  new_data   jsonb,
  request_id text,
  client_ip  text
);
create index ix_audit_company_at on fin.audit_log (company_id, at desc);
create index ix_audit_record on fin.audit_log (table_name, record_id);

create function fin.tg_audit() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_old jsonb := case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) end;
  v_new jsonb := case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) end;
  v_row jsonb := coalesce(v_new, v_old);
  v_company uuid;
begin
  v_company := case when tg_table_name = 'companies' then (v_row ->> 'id')::uuid
                    else (v_row ->> 'company_id')::uuid end;
  insert into fin.audit_log (actor_id, company_id, action, table_name, record_id,
                             old_data, new_data, request_id, client_ip)
  values (fin.uid(), v_company, lower(tg_op), tg_table_name,
          coalesce(v_row ->> 'id', v_row ->> 'user_id', v_row ->> 'key'),
          v_old, v_new,
          nullif(current_setting('fin.request_id', true), ''),
          nullif(current_setting('fin.client_ip', true), ''));
  return null;
end $$;

create function fin.tg_append_only() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception '% is append-only', tg_table_name using errcode = '42501';
end $$;
create trigger tg_append_only before update or delete on fin.audit_log
  for each row execute function fin.tg_append_only();
create trigger tg_append_only_truncate before truncate on fin.audit_log
  for each statement execute function fin.tg_append_only();

create trigger tg_audit after insert or update or delete on fin.companies for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.sites for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.profiles for each row execute function fin.tg_audit();
create trigger tg_audit after insert or update or delete on fin.company_memberships for each row execute function fin.tg_audit();

create table fin.security_events (
  id        bigint generated always as identity primary key,
  at        timestamptz not null default now(),
  user_id   uuid,
  email     text,
  event     text not null check (event ~ '^[a-z_]{3,50}$'),
  client_ip text,
  detail    jsonb
);
create index ix_security_events_at on fin.security_events (at desc);
create trigger tg_append_only before update or delete on fin.security_events
  for each row execute function fin.tg_append_only();
