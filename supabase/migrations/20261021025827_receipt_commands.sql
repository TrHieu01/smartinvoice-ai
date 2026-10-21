-- Server-only transaction commands. Ownership arguments come from verified Auth,
-- never from the browser. All functions are SECURITY INVOKER.
begin;

create function public.si_data(p_id uuid) returns jsonb
language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'merchant', r.merchant, 'merchant_tax_id', r.merchant_tax_id,
    'invoice_number', r.invoice_number, 'purchase_date', r.purchase_date,
    'subtotal', r.subtotal::text, 'tax_amount', r.tax_amount::text,
    'discount_amount', r.discount_amount::text, 'total_amount', r.total_amount::text,
    'currency', r.currency, 'items', coalesce((select jsonb_agg(jsonb_build_object(
      'line_number', i.line_number, 'name', i.name, 'quantity', i.quantity::text,
      'unit_price', i.unit_price::text, 'line_total', i.line_total::text
    ) order by i.line_number) from public.receipt_items i where i.receipt_id = r.id), '[]'::jsonb)
  ) from public.receipts r where r.id = p_id;
$$;

create function public.si_summary(p_id uuid) returns jsonb
language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object('id', r.id, 'filename', r.filename, 'status', r.status,
    'merchant', r.merchant, 'purchase_date', r.purchase_date, 'total_amount', r.total_amount::text,
    'currency', r.currency, 'category', r.category, 'version', r.version,
    'created_at', r.created_at, 'updated_at', r.updated_at)
  from public.receipts r where r.id = p_id;
$$;

create function public.si_job(p_id uuid) returns jsonb
language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object('id', j.id, 'run_number', j.run_number, 'status', j.status,
    'attempts', j.attempts, 'error_code', j.error_code, 'latency_ms', j.latency_ms)
  from public.processing_jobs j where j.receipt_id = p_id order by j.run_number desc limit 1;
$$;

create function public.si_detail(p_actor uuid, p_id uuid) returns jsonb
language plpgsql stable security invoker set search_path = '' as $$
declare r public.receipts; x public.extraction_results; result jsonb;
begin
  select * into r from public.receipts where id = p_id and user_id = p_actor and status <> 'deleting';
  if not found then raise exception 'receipt_not_found'; end if;
  select * into x from public.extraction_results where id = r.current_extraction_id;
  if found then
    result := jsonb_build_object('schema_version', x.schema_version, 'receipt_id', x.receipt_id,
      'job_id', x.job_id, 'pipeline_version', x.pipeline_version, 'processed_at', x.processed_at,
      'data', x.extracted_json, 'ocr', x.raw_ocr_json, 'evidence', x.evidence,
      'warnings', x.warnings, 'timings', x.timings);
  end if;
  return public.si_summary(r.id) || jsonb_build_object('data', public.si_data(r.id),
    'job', public.si_job(r.id), 'latest_extraction', result, 'warnings', r.validation_warnings,
    'confirmed_at', r.confirmed_at);
end;
$$;

create function public.si_create(p_actor uuid, p_key uuid, p_filename text, p_mime text,
  p_size bigint, p_hash text) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare r public.receipts; rid uuid := gen_random_uuid(); ext text;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_actor::text, 0));
  select * into r from public.receipts where user_id = p_actor and creation_key = p_key for update;
  if found then
    if r.creation_payload_hash <> p_hash then raise exception 'idempotency_conflict'; end if;
    if r.status = 'deleting' then raise exception 'receipt_not_found'; end if;
    return to_jsonb(r) || jsonb_build_object('replayed', true);
  end if;
  if (select count(*) from public.receipts where user_id = p_actor
      and created_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC') >= 20 then
    raise exception 'quota_exceeded';
  end if;
  ext := case p_mime when 'image/jpeg' then 'jpg' when 'image/png' then 'png'
    when 'image/webp' then 'webp' when 'application/pdf' then 'pdf' end;
  if ext is null then raise exception 'unsupported_media_type'; end if;
  insert into public.receipts(id, user_id, creation_key, creation_payload_hash, filename,
    content_type, size_bytes, file_extension, storage_path, upload_expires_at)
  values (rid, p_actor, p_key, p_hash, p_filename, p_mime, p_size, ext,
    p_actor::text || '/' || rid::text || '/original.' || ext, now() + interval '2 hours 1 minute')
  returning * into r;
  return to_jsonb(r) || jsonb_build_object('replayed', false);
end;
$$;

create function public.si_ticket(p_actor uuid, p_id uuid, p_expires timestamptz) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare r public.receipts;
begin
  select * into r from public.receipts where id = p_id and user_id = p_actor and status <> 'deleting' for update;
  if not found then raise exception 'receipt_not_found'; end if;
  if r.status = 'awaiting_upload' and p_expires > r.upload_expires_at then
    update public.receipts set upload_expires_at = p_expires where id = p_id returning * into r;
  end if;
  return to_jsonb(r);
end;
$$;

create function public.si_enqueue(p_actor uuid, p_id uuid, p_key uuid,
  p_sha text default null, p_pages integer default null, p_retry boolean default false) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare r public.receipts; j public.processing_jobs; run integer;
begin
  select * into r from public.receipts where id = p_id and user_id = p_actor and status <> 'deleting' for update;
  if not found then raise exception 'receipt_not_found'; end if;
  select * into j from public.processing_jobs where user_id = p_actor and request_key = p_key;
  if found then
    if j.receipt_id <> p_id then raise exception 'idempotency_conflict'; end if;
    return jsonb_build_object('receipt_id', r.id, 'status', r.status, 'job', public.si_job(r.id),
      'poll_after_ms', case when r.status in ('queued','processing') then 2000 else null end);
  end if;
  if not p_retry and r.status <> 'awaiting_upload' then
    return jsonb_build_object('receipt_id', r.id, 'status', r.status, 'job', public.si_job(r.id),
      'poll_after_ms', case when r.status in ('queued','processing') then 2000 else null end);
  end if;
  if p_retry and r.status <> 'failed' then raise exception 'invalid_state'; end if;
  if not p_retry and (p_sha is null or p_pages is null) then raise exception 'invalid_request'; end if;
  select coalesce(max(run_number),0)+1 into run from public.processing_jobs where receipt_id = p_id;
  insert into public.processing_jobs(receipt_id,user_id,request_key,run_number)
    values(p_id,p_actor,p_key,run) returning * into j;
  insert into public.task_outbox(receipt_id,user_id,job_id,event_type,task_name)
    values(p_id,p_actor,j.id,'process_receipt','process-'||j.id::text);
  update public.receipts set status='queued', uploaded_at=coalesce(uploaded_at,now()),
    file_sha256=coalesce(file_sha256,p_sha), page_count=coalesce(page_count,p_pages) where id=p_id;
  return jsonb_build_object('receipt_id',p_id,'status','queued','job',public.si_job(p_id),'poll_after_ms',2000);
end;
$$;

create function public.si_claim(p_job uuid) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare r public.receipts; j public.processing_jobs; token uuid := gen_random_uuid(); rid uuid;
begin
  select receipt_id into rid from public.processing_jobs where id=p_job;
  if not found then return jsonb_build_object('decision','terminal'); end if;
  select * into r from public.receipts where id=rid for update;
  select * into j from public.processing_jobs where id=p_job for update;
  if j.status in ('succeeded','failed','cancelled') or r.status='deleting' then
    return jsonb_build_object('decision','terminal');
  end if;
  if j.status='running' and j.lease_expires_at > now() then return jsonb_build_object('decision','busy'); end if;
  if j.attempts >= 3 then
    update public.processing_jobs set status='failed',error_code='attempts_exhausted',
      lease_token=null,lease_expires_at=null,finished_at=now() where id=p_job;
    update public.receipts set status='failed' where id=rid;
    return jsonb_build_object('decision','terminal');
  end if;
  if r.status not in ('queued','processing') then return jsonb_build_object('decision','terminal'); end if;
  update public.processing_jobs set status='running',attempts=attempts+1,lease_token=token,
    lease_expires_at=now()+interval '360 seconds',started_at=now(),error_code=null where id=p_job;
  update public.receipts set status='processing' where id=rid;
  return jsonb_build_object('decision','claimed','lease_token',token,'receipt',to_jsonb(r));
end;
$$;

create function public.si_replace_items(p_id uuid,p_user uuid,p_data jsonb) returns void
language plpgsql security invoker set search_path = '' as $$
begin
  delete from public.receipt_items where receipt_id=p_id;
  insert into public.receipt_items(receipt_id,user_id,line_number,name,quantity,unit_price,line_total)
  select p_id,p_user,(x->>'line_number')::integer,x->>'name',(x->>'quantity')::numeric,
    (x->>'unit_price')::numeric,(x->>'line_total')::numeric
  from jsonb_array_elements(p_data->'items') x;
end;
$$;

create function public.si_complete(p_job uuid,p_token uuid,p_result jsonb) returns boolean
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
    merchant=d->>'merchant',merchant_tax_id=d->>'merchant_tax_id',invoice_number=d->>'invoice_number',
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

create function public.si_fail(p_job uuid,p_token uuid,p_code text) returns boolean
language plpgsql security invoker set search_path = '' as $$
declare r public.receipts; j public.processing_jobs; rid uuid;
begin
  select receipt_id into rid from public.processing_jobs where id=p_job;
  select * into r from public.receipts where id=rid for update;
  select * into j from public.processing_jobs where id=p_job for update;
  if not found or r.status='deleting' or j.status<>'running' or j.lease_token is distinct from p_token
    or j.lease_expires_at<=now() then return false; end if;
  update public.processing_jobs set status='failed',lease_token=null,lease_expires_at=null,
    error_code=p_code,finished_at=now() where id=p_job;
  update public.receipts set status='failed' where id=rid;
  return true;
end;
$$;

create function public.si_review(p_actor uuid,p_id uuid,p_expected integer,p_action text,
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
    merchant=p_data->>'merchant',merchant_tax_id=p_data->>'merchant_tax_id',invoice_number=p_data->>'invoice_number',
    purchase_date=(p_data->>'purchase_date')::date,subtotal=(p_data->>'subtotal')::numeric,
    tax_amount=(p_data->>'tax_amount')::numeric,discount_amount=(p_data->>'discount_amount')::numeric,
    total_amount=(p_data->>'total_amount')::numeric,currency=p_data->>'currency',category=p_category,
    validation_warnings=p_warnings,confirmed_at=case when p_action='confirm' then now() else null end
    where id=p_id;
  return public.si_detail(p_actor,p_id);
end;
$$;

create function public.si_delete(p_actor uuid,p_id uuid) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare r public.receipts;
begin
  select * into r from public.receipts where id=p_id and user_id=p_actor for update;
  if not found then raise exception 'receipt_not_found'; end if;
  if r.status='deleting' then return jsonb_build_object('id',p_id,'status','deleting'); end if;
  update public.receipts set status='deleting',deleted_at=now() where id=p_id;
  update public.processing_jobs set status='cancelled',lease_token=null,lease_expires_at=null,finished_at=now()
    where receipt_id=p_id and status in ('pending','running');
  update public.task_outbox set status='cancelled',dispatch_lease_token=null,dispatch_lease_expires_at=null
    where receipt_id=p_id;
  insert into public.task_outbox(receipt_id,user_id,event_type,task_name,available_at)
    values(p_id,p_actor,'cleanup_receipt','cleanup-'||p_id::text,greatest(now(),r.upload_expires_at+interval '5 minutes'));
  return jsonb_build_object('id',p_id,'status','deleting');
end;
$$;

create function public.si_list(p_actor uuid,p_page integer default 1,p_size integer default 20,
  p_merchant text default null,p_status text default null,p_from date default null,p_to date default null,
  p_min numeric default null,p_max numeric default null,p_sort text default 'created_at_desc') returns jsonb
language plpgsql stable security invoker set search_path = '' as $$
declare result jsonb; total bigint;
begin
  if p_page<1 or p_size<1 or p_size>100 or p_sort not in ('created_at_desc','purchase_date_desc','total_amount_desc') then
    raise exception 'invalid_request'; end if;
  select count(*) into total from public.receipts r where r.user_id=p_actor and r.status<>'deleting'
    and (p_merchant is null or strpos(lower(r.merchant),lower(p_merchant))>0)
    and (p_status is null or r.status::text=p_status) and (p_from is null or r.purchase_date>=p_from)
    and (p_to is null or r.purchase_date<=p_to) and (p_min is null or r.total_amount>=p_min)
    and (p_max is null or r.total_amount<=p_max);
  select coalesce(jsonb_agg(public.si_summary(q.id) order by q.rn),'[]'::jsonb) into result from (
    select r.id,row_number() over (order by
      case when p_sort='purchase_date_desc' then r.purchase_date end desc nulls last,
      case when p_sort='total_amount_desc' then r.total_amount end desc nulls last,
      case when p_sort='created_at_desc' then r.created_at end desc,r.id desc) rn
    from public.receipts r where r.user_id=p_actor and r.status<>'deleting'
      and (p_merchant is null or strpos(lower(r.merchant),lower(p_merchant))>0)
      and (p_status is null or r.status::text=p_status) and (p_from is null or r.purchase_date>=p_from)
      and (p_to is null or r.purchase_date<=p_to) and (p_min is null or r.total_amount>=p_min)
      and (p_max is null or r.total_amount<=p_max)
    order by rn limit p_size offset ((p_page-1)::bigint*p_size)
  ) q;
  return jsonb_build_object('items',result,'page',p_page,'page_size',p_size,'total_count',total);
end;
$$;

create function public.si_analytics(p_actor uuid,p_from date,p_to date) returns jsonb
language plpgsql stable security invoker set search_path = '' as $$
declare amount numeric; n bigint; months jsonb; categories jsonb;
begin
  if p_to<p_from or p_to-p_from>365 then raise exception 'invalid_request'; end if;
  select coalesce(sum(total_amount),0),count(*) into amount,n from public.receipts
    where user_id=p_actor and status='confirmed' and purchase_date between p_from and p_to;
  select jsonb_agg(jsonb_build_object('month',to_char(m,'YYYY-MM'),
    'total_amount',coalesce(a.total,0)::text,'receipt_count',coalesce(a.n,0)) order by m)
  into months from generate_series(date_trunc('month',p_from::timestamp),date_trunc('month',p_to::timestamp),interval '1 month') m
  left join (select date_trunc('month',purchase_date::timestamp) mon,sum(total_amount) total,count(*) n
    from public.receipts where user_id=p_actor and status='confirmed' and purchase_date between p_from and p_to
    group by 1) a on a.mon=m;
  select coalesce(jsonb_agg(jsonb_build_object('category',s.category,'total_amount',s.total::text,'receipt_count',s.n)),'[]'::jsonb)
  into categories from (select category,sum(total_amount) total,count(*) n from public.receipts
    where user_id=p_actor and status='confirmed' and purchase_date between p_from and p_to group by category) s;
  return jsonb_build_object('date_from',p_from,'date_to',p_to,'currency','VND','included_status','confirmed',
    'total_amount',amount::text,'receipt_count',n,'monthly',months,'categories',categories);
end;
$$;

-- Supabase defaults can grant new public functions to browser roles. Restrict
-- every si_* overload explicitly; trigger functions from migration 1 stay as-is.
do $$ declare f record; begin
  for f in select p.oid::regprocedure signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname like 'si\_%' escape '\' loop
    execute format('revoke all on function %s from public, anon, authenticated',f.signature);
    execute format('grant execute on function %s to service_role',f.signature);
  end loop;
end $$;

commit;
