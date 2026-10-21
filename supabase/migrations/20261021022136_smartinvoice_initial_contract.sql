-- SmartInvoice AI schema contract v1.0.0.
-- Generated migration filename by Supabase CLI 2.121.0.
-- Run on a fresh Supabase project. No data or live resources are changed by authoring this file.
begin;

create type public.receipt_status as enum (
  'awaiting_upload', 'queued', 'processing', 'needs_review', 'confirmed', 'failed', 'deleting'
);
create type public.job_status as enum ('pending', 'running', 'succeeded', 'failed', 'cancelled');
create type public.expense_category as enum (
  'uncategorized', 'food', 'shopping', 'transport', 'utilities', 'health', 'education', 'other'
);

create table public.receipts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete restrict,
  creation_key uuid not null,
  creation_payload_hash text not null check (creation_payload_hash ~ '^[a-f0-9]{64}$'),
  filename text not null check (length(filename) between 1 and 255),
  content_type text not null check (content_type in (
    'image/jpeg', 'image/png', 'image/webp', 'application/pdf'
  )),
  size_bytes bigint not null check (size_bytes between 1 and 5000000),
  file_extension text not null check (file_extension in ('jpg', 'png', 'webp', 'pdf')),
  storage_path text not null unique,
  upload_expires_at timestamptz not null,
  uploaded_at timestamptz,
  file_sha256 text check (file_sha256 ~ '^[a-f0-9]{64}$'),
  page_count smallint check (page_count between 1 and 5),
  status public.receipt_status not null default 'awaiting_upload',
  merchant text check (length(merchant) between 1 and 300),
  merchant_tax_id text check (merchant_tax_id ~ '^[0-9]{10}(-[0-9]{3})?$'),
  invoice_number text check (length(invoice_number) between 1 and 100),
  purchase_date date,
  subtotal numeric(16,2) check (subtotal between 0 and 99999999999999.99),
  tax_amount numeric(16,2) check (tax_amount between 0 and 99999999999999.99),
  discount_amount numeric(16,2) check (discount_amount between 0 and 99999999999999.99),
  total_amount numeric(16,2) check (total_amount between 0 and 99999999999999.99),
  currency text check (currency = 'VND'),
  category public.expense_category not null default 'uncategorized',
  validation_warnings jsonb not null default '[]'::jsonb
    check (jsonb_typeof(validation_warnings) = 'array'),
  current_extraction_id uuid,
  version integer not null default 1 check (version >= 1),
  confirmed_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, user_id),
  unique (user_id, creation_key),
  constraint receipt_storage_path check (
    storage_path = user_id::text || '/' || id::text || '/original.' || file_extension
  ),
  constraint receipt_file_type check (
    (content_type = 'image/jpeg' and file_extension = 'jpg') or
    (content_type = 'image/png' and file_extension = 'png') or
    (content_type = 'image/webp' and file_extension = 'webp') or
    (content_type = 'application/pdf' and file_extension = 'pdf')
  ),
  constraint receipt_verified_upload check (
    status not in ('queued', 'processing', 'needs_review', 'confirmed') or
    (uploaded_at is not null and file_sha256 is not null and page_count is not null)
  ),
  constraint confirmed_receipt_complete check (
    status <> 'confirmed' or (merchant is not null and purchase_date is not null
      and total_amount is not null and currency is not null
      and confirmed_at is not null and current_extraction_id is not null)
  ),
  constraint deleting_receipt_timestamp check (
    (status = 'deleting') = (deleted_at is not null)
  )
);

create index receipts_owner_created_idx on public.receipts (user_id, created_at desc, id desc);
create index receipts_owner_date_idx on public.receipts (user_id, purchase_date desc, id desc)
  where status <> 'deleting';
create index receipts_owner_status_idx on public.receipts (user_id, status);
create index receipts_confirmed_analytics_idx on public.receipts (user_id, purchase_date, category)
  include (total_amount) where status = 'confirmed';

create table public.receipt_items (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid not null,
  user_id uuid not null,
  line_number integer not null check (line_number between 1 and 500),
  name text not null check (length(name) between 1 and 300),
  quantity numeric(12,3) check (quantity > 0 and quantity <= 999999999.999),
  unit_price numeric(16,2) check (unit_price between 0 and 99999999999999.99),
  line_total numeric(16,2) check (line_total between 0 and 99999999999999.99),
  foreign key (receipt_id, user_id) references public.receipts (id, user_id) on delete cascade,
  unique (receipt_id, line_number)
);
create index receipt_items_owner_receipt_idx on public.receipt_items (user_id, receipt_id);

create table public.processing_jobs (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid not null,
  user_id uuid not null,
  request_key uuid not null,
  run_number integer not null check (run_number >= 1),
  status public.job_status not null default 'pending',
  attempts smallint not null default 0 check (attempts between 0 and 3),
  lease_token uuid,
  lease_expires_at timestamptz,
  error_code text,
  latency_ms integer check (latency_ms >= 0),
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  foreign key (receipt_id, user_id) references public.receipts (id, user_id) on delete cascade,
  unique (id, receipt_id, user_id),
  unique (receipt_id, run_number),
  unique (user_id, request_key),
  constraint job_live_lease check (
    (status = 'running' and lease_token is not null and lease_expires_at is not null) or
    (status <> 'running' and lease_token is null and lease_expires_at is null)
  ),
  constraint terminal_job_timestamp check (
    (status in ('succeeded', 'failed', 'cancelled')) = (finished_at is not null)
  )
);
create unique index processing_jobs_one_active_idx on public.processing_jobs (receipt_id)
  where status in ('pending', 'running');
create index processing_jobs_owner_idx on public.processing_jobs (user_id, receipt_id);
create index processing_jobs_reconcile_idx on public.processing_jobs (status, lease_expires_at, created_at)
  where status in ('pending', 'running');

create table public.extraction_results (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid not null,
  user_id uuid not null,
  job_id uuid not null unique,
  schema_version text not null check (schema_version = '1.0.0'),
  pipeline_version text not null check (length(pipeline_version) between 1 and 300),
  raw_ocr_json jsonb not null check (jsonb_typeof(raw_ocr_json) = 'object'),
  extracted_json jsonb not null check (jsonb_typeof(extracted_json) = 'object'),
  evidence jsonb not null check (jsonb_typeof(evidence) = 'array'),
  warnings jsonb not null check (jsonb_typeof(warnings) = 'array'),
  timings jsonb not null check (jsonb_typeof(timings) = 'object'),
  processed_at timestamptz not null,
  foreign key (receipt_id, user_id) references public.receipts (id, user_id) on delete cascade,
  foreign key (job_id, receipt_id, user_id)
    references public.processing_jobs (id, receipt_id, user_id) on delete cascade,
  unique (receipt_id, user_id, id)
);
create index extraction_results_owner_receipt_idx on public.extraction_results (user_id, receipt_id);

alter table public.receipts add constraint receipts_current_extraction_fk
  foreign key (id, user_id, current_extraction_id)
  references public.extraction_results (receipt_id, user_id, id)
  deferrable initially deferred;

create table public.receipt_corrections (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid not null,
  user_id uuid not null,
  base_extraction_id uuid not null,
  from_version integer not null check (from_version >= 1),
  to_version integer not null check (to_version = from_version + 1),
  action text not null check (action in ('save', 'confirm')),
  before_data jsonb not null check (jsonb_typeof(before_data) = 'object'),
  after_data jsonb not null check (jsonb_typeof(after_data) = 'object'),
  changed_fields jsonb not null check (jsonb_typeof(changed_fields) = 'array'),
  created_at timestamptz not null default now(),
  foreign key (receipt_id, user_id) references public.receipts (id, user_id) on delete cascade,
  foreign key (receipt_id, user_id, base_extraction_id)
    references public.extraction_results (receipt_id, user_id, id) on delete cascade,
  unique (receipt_id, to_version)
);
create index receipt_corrections_owner_receipt_idx on public.receipt_corrections (user_id, receipt_id);
create index receipt_corrections_baseline_idx on public.receipt_corrections
  (receipt_id, user_id, base_extraction_id);

-- Durable outbox records work in the same transaction as the receipt/job.
-- The same abstraction drives RunPod dispatch and non-GPU deletion cleanup.
create table public.task_outbox (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid not null,
  user_id uuid not null,
  job_id uuid,
  event_type text not null check (event_type in ('process_receipt', 'cleanup_receipt')),
  status text not null default 'pending' check (status in ('pending', 'published', 'cancelled')),
  task_name text not null unique,
  available_at timestamptz not null default now(),
  published_at timestamptz,
  provider_request_id text,
  dispatch_lease_token uuid,
  dispatch_lease_expires_at timestamptz,
  dispatch_attempts integer not null default 0 check (dispatch_attempts >= 0),
  last_error_code text,
  created_at timestamptz not null default now(),
  foreign key (receipt_id, user_id) references public.receipts (id, user_id) on delete cascade,
  foreign key (job_id, receipt_id, user_id)
    references public.processing_jobs (id, receipt_id, user_id) on delete cascade,
  constraint outbox_target check (
    (event_type = 'process_receipt' and job_id is not null) or
    (event_type = 'cleanup_receipt' and job_id is null)
  ),
  constraint outbox_dispatch_lease check (
    (dispatch_lease_token is null) = (dispatch_lease_expires_at is null)
  )
);
create unique index task_outbox_process_once_idx on public.task_outbox (job_id)
  where event_type = 'process_receipt';
create unique index task_outbox_cleanup_once_idx on public.task_outbox (receipt_id)
  where event_type = 'cleanup_receipt';
create index task_outbox_due_idx on public.task_outbox (available_at, id) where status = 'pending';
create index task_outbox_receipt_idx on public.task_outbox (receipt_id, user_id);
create index task_outbox_job_idx on public.task_outbox (job_id, receipt_id, user_id);

create function public.guard_receipt_update()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if row(new.id, new.user_id, new.storage_path, new.creation_key, new.creation_payload_hash,
      new.filename, new.content_type, new.size_bytes, new.file_extension,
      new.created_at)
    is distinct from row(old.id, old.user_id, old.storage_path, old.creation_key,
      old.creation_payload_hash, old.filename, old.content_type, old.size_bytes,
      old.file_extension, old.created_at) then
    raise exception 'immutable_receipt_identity' using errcode = '23514';
  end if;
  if new.upload_expires_at is distinct from old.upload_expires_at and (
    old.status <> 'awaiting_upload' or new.status <> 'awaiting_upload'
    or new.upload_expires_at < old.upload_expires_at
  ) then
    raise exception 'invalid_upload_ticket_extension' using errcode = '23514';
  end if;
  if old.file_sha256 is not null and new.file_sha256 is distinct from old.file_sha256 then
    raise exception 'immutable_uploaded_file' using errcode = '23514';
  end if;
  if new.status <> old.status and not (
    (old.status = 'awaiting_upload' and new.status in ('queued', 'deleting')) or
    (old.status = 'queued' and new.status in ('processing', 'failed', 'deleting')) or
    (old.status = 'processing' and new.status in ('queued', 'needs_review', 'failed', 'deleting')) or
    (old.status = 'needs_review' and new.status in ('confirmed', 'deleting')) or
    (old.status = 'confirmed' and new.status in ('needs_review', 'deleting')) or
    (old.status = 'failed' and new.status in ('queued', 'deleting'))
  ) then
    raise exception 'invalid_receipt_transition' using errcode = '23514';
  end if;
  if new.status = 'deleting' and old.status = 'deleting' then
    raise exception 'deleted_receipt_immutable' using errcode = '23514';
  end if;
  new.version := old.version + 1;
  new.updated_at := now();
  return new;
end;
$$;
create trigger guard_receipt_update before update on public.receipts
  for each row execute function public.guard_receipt_update();

create function public.reject_history_update()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  raise exception 'history_is_append_only' using errcode = '23514';
end;
$$;
create trigger immutable_extraction before update on public.extraction_results
  for each row execute function public.reject_history_update();
create trigger immutable_correction before update on public.receipt_corrections
  for each row execute function public.reject_history_update();

revoke all on function public.guard_receipt_update() from public, anon, authenticated;
revoke all on function public.reject_history_update() from public, anon, authenticated;

alter table public.receipts enable row level security;
alter table public.receipt_items enable row level security;
alter table public.processing_jobs enable row level security;
alter table public.extraction_results enable row level security;
alter table public.receipt_corrections enable row level security;
alter table public.task_outbox enable row level security;

-- All writes go through authenticated application commands. Browser JWTs cannot
-- forge processing states, modify AI evidence, or bypass the correction log.
revoke all on table public.receipts, public.receipt_items, public.processing_jobs,
  public.extraction_results, public.receipt_corrections, public.task_outbox from anon, authenticated;
grant select on public.receipts, public.receipt_items, public.receipt_corrections to authenticated;
grant all on table public.receipts, public.receipt_items, public.processing_jobs,
  public.extraction_results, public.receipt_corrections, public.task_outbox to service_role;

create policy receipts_owner_read on public.receipts for select to authenticated
  using ((select auth.uid()) = user_id and status <> 'deleting');
create policy receipt_items_owner_read on public.receipt_items for select to authenticated
  using ((select auth.uid()) = user_id and exists (
    select 1 from public.receipts r
    where r.id = receipt_items.receipt_id and r.user_id = receipt_items.user_id
      and r.status <> 'deleting'
  ));
create policy receipt_corrections_owner_read on public.receipt_corrections for select to authenticated
  using ((select auth.uid()) = user_id and exists (
    select 1 from public.receipts r
    where r.id = receipt_corrections.receipt_id and r.user_id = receipt_corrections.user_id
      and r.status <> 'deleting'
  ));

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('receipts', 'receipts', false, 5000000,
  array['image/jpeg', 'image/png', 'image/webp', 'application/pdf']);

-- Upload capabilities are minted by the API with a server-only credential,
-- exact immutable path, and upsert=false. No client INSERT/UPDATE/DELETE policy.
-- Do not change grants or policies belonging to unrelated buckets.
create policy smartinvoice_receipt_read on storage.objects for select to authenticated
  using (bucket_id = 'receipts' and exists (
    select 1 from public.receipts r
    where r.storage_path = storage.objects.name
      and r.user_id = (select auth.uid()) and r.status <> 'deleting'
  ));

comment on table public.receipts is 'Current reviewed data. Tenant identity comes from verified JWT, never request body.';
comment on table public.extraction_results is 'Original AI output per processing run; updates prohibited. Full schema validated by worker.';
comment on table public.receipt_corrections is 'Append-only review snapshots; record even confirmations with no changed fields.';
comment on table public.task_outbox is 'Atomic work intent; server-side dispatcher/reconciler required. RunPod compute uses existing credit.';

commit;
