-- Optional receipt fields; preserve existing rows, RLS and server-only RPC grants.
begin;
alter table public.receipts
  add column merchant_address text check (length(merchant_address) between 1 and 500),
  add column payment_method text check (length(payment_method) between 1 and 50);
alter table public.receipt_items add column unit text check (length(unit) between 1 and 50);
alter table public.extraction_results drop constraint extraction_results_schema_version_check;
alter table public.extraction_results add constraint extraction_results_schema_version_check
  check (schema_version in ('1.0.0', '1.1.0'));
create or replace function public.si_data(p_id uuid) returns jsonb
language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'merchant', r.merchant, 'merchant_address', r.merchant_address, 'payment_method', r.payment_method, 'merchant_tax_id', r.merchant_tax_id,
    'invoice_number', r.invoice_number, 'purchase_date', r.purchase_date,
    'subtotal', r.subtotal::text, 'tax_amount', r.tax_amount::text,
    'discount_amount', r.discount_amount::text, 'total_amount', r.total_amount::text,
    'currency', r.currency, 'items', coalesce((select jsonb_agg(jsonb_build_object(
      'line_number', i.line_number, 'name', i.name, 'unit', i.unit, 'quantity', i.quantity::text,
      'unit_price', i.unit_price::text, 'line_total', i.line_total::text
    ) order by i.line_number) from public.receipt_items i where i.receipt_id = r.id), '[]'::jsonb)
  ) from public.receipts r where r.id = p_id;
$$;

create or replace function public.si_replace_items(p_id uuid,p_user uuid,p_data jsonb) returns void
language plpgsql security invoker set search_path = '' as $$
begin
  delete from public.receipt_items where receipt_id=p_id;
  insert into public.receipt_items(receipt_id,user_id,line_number,name,unit,quantity,unit_price,line_total)
  select p_id,p_user,(x->>'line_number')::integer,x->>'name',x->>'unit',(x->>'quantity')::numeric,
    (x->>'unit_price')::numeric,(x->>'line_total')::numeric
  from jsonb_array_elements(p_data->'items') x;
end;
$$;

create or replace function public.si_complete(p_job uuid,p_token uuid,p_result jsonb) returns boolean
language plpgsql security invoker set search_path = '' as $$
declare r public.receipts; j public.processing_jobs; x_id uuid; d jsonb := p_result->'data'; rid uuid;
begin
  select receipt_id into rid from public.processing_jobs where id=p_job;
  select * into r from public.receipts where id=rid for update;
  select * into j from public.processing_jobs where id=p_job for update;
  if not found or r.status <> 'processing' or j.status <> 'running' or j.lease_token is distinct from p_token
    or j.lease_expires_at <= now() then return false; end if;
  if p_result->>'job_id' is distinct from p_job::text or p_result->>'receipt_id' is distinct from r.id::text then
    raise exception 'invalid_request';
  end if;
  insert into public.extraction_results(receipt_id,user_id,job_id,schema_version,pipeline_version,
    raw_ocr_json,extracted_json,evidence,warnings,timings,processed_at)
  values(r.id,r.user_id,j.id,p_result->>'schema_version',p_result->>'pipeline_version',p_result->'ocr',
    d,p_result->'evidence',p_result->'warnings',p_result->'timings',(p_result->>'processed_at')::timestamptz)
  returning id into x_id;
  perform public.si_replace_items(r.id,r.user_id,d);
  update public.receipts set status='needs_review',current_extraction_id=x_id,
    merchant=d->>'merchant',merchant_address=d->>'merchant_address',payment_method=d->>'payment_method',merchant_tax_id=d->>'merchant_tax_id',invoice_number=d->>'invoice_number',
    purchase_date=(d->>'purchase_date')::date,subtotal=(d->>'subtotal')::numeric,
    tax_amount=(d->>'tax_amount')::numeric,discount_amount=(d->>'discount_amount')::numeric,
    total_amount=(d->>'total_amount')::numeric,currency=d->>'currency',validation_warnings=p_result->'warnings'
    where id=r.id;
  update public.processing_jobs set status='succeeded',lease_token=null,lease_expires_at=null,
    finished_at=now(),latency_ms=(p_result->'timings'->>'total_ms')::integer where id=p_job;
  update public.task_outbox set status='published',published_at=coalesce(published_at,now()),
    dispatch_lease_token=null,dispatch_lease_expires_at=null where job_id=p_job;
  return true;
end;
$$;

create or replace function public.si_review(p_actor uuid,p_id uuid,p_expected integer,p_action text,
  p_data jsonb,p_category public.expense_category,p_warnings jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare r public.receipts; old_data jsonb; changes jsonb;
begin
  select * into r from public.receipts where id=p_id and user_id=p_actor and status<>'deleting' for update;
  if not found then raise exception 'receipt_not_found'; end if;
  if r.version<>p_expected then raise exception 'version_conflict'; end if;
  if r.status not in ('needs_review','confirmed') or p_action not in ('save','confirm') then raise exception 'invalid_state'; end if;
  if p_action='confirm' and (p_data->>'merchant' is null or p_data->>'purchase_date' is null
    or p_data->>'total_amount' is null or p_data->>'currency' is null) then raise exception 'invalid_request'; end if;
  old_data := public.si_data(p_id);
  select coalesce(jsonb_agg('/'||key),'[]'::jsonb) into changes from jsonb_each(p_data)
    where value is distinct from old_data->key;
  insert into public.receipt_corrections(receipt_id,user_id,base_extraction_id,from_version,
    to_version,action,before_data,after_data,changed_fields)
  values(p_id,p_actor,r.current_extraction_id,r.version,r.version+1,p_action,
    old_data||jsonb_build_object('category',r.category),p_data||jsonb_build_object('category',p_category),changes);
  perform public.si_replace_items(p_id,p_actor,p_data);
  update public.receipts set status=case when p_action='confirm' then 'confirmed'::public.receipt_status
    else 'needs_review'::public.receipt_status end,
    merchant=p_data->>'merchant',merchant_address=p_data->>'merchant_address',payment_method=p_data->>'payment_method',merchant_tax_id=p_data->>'merchant_tax_id',invoice_number=p_data->>'invoice_number',
    purchase_date=(p_data->>'purchase_date')::date,subtotal=(p_data->>'subtotal')::numeric,
    tax_amount=(p_data->>'tax_amount')::numeric,discount_amount=(p_data->>'discount_amount')::numeric,
    total_amount=(p_data->>'total_amount')::numeric,currency=p_data->>'currency',category=p_category,
    validation_warnings=p_warnings,confirmed_at=case when p_action='confirm' then now() else null end
    where id=p_id;
  return public.si_detail(p_actor,p_id);
end;
$$;

notify pgrst, 'reload schema';
commit;
