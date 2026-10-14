-- Run once in the Supabase SQL editor. The browser never receives a service role key.
create table if not exists public.insta_records (
  id text primary key,
  kind text not null check (kind in ('account', 'job')),
  payload jsonb not null,
  status text not null,
  created_at timestamptz not null default now()
);
create index if not exists insta_records_kind_status on public.insta_records (kind, status);
alter table public.insta_records enable row level security;
revoke all on public.insta_records from anon, authenticated;
grant select, insert, update, delete on public.insta_records to service_role;
-- No public policies: access is exclusively through the Python API.
