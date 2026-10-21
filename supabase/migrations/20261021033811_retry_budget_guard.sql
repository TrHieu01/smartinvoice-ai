begin;
create or replace function public.si_enqueue(p_actor uuid, p_id uuid, p_key uuid,
  p_sha text default null, p_pages integer default null, p_retry boolean default false) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare r public.receipts; j public.processing_jobs; run integer;
begin
  select * into r from public.receipts where id = p_id and user_id = p_actor and status <> 'deleting' for update;
  if not found then raise exception 'receipt_not_found'; end if;
  select * into j from public.processing_jobs where user_id = p_actor and request_key = p_key;
  if found then
    if j.receipt_id <> p_id then raise exception 'idempotency_conflict'; end if;
    return jsonb_build_object('receipt_id', r.id, 'status', r.status, 'job', jsonb_build_object('id',j.id,'run_number',j.run_number,'status',j.status,'attempts',j.attempts,'error_code',j.error_code,'latency_ms',j.latency_ms),
      'poll_after_ms', case when r.status in ('queued','processing') then 2000 else null end);
  end if;
  if not p_retry and r.status <> 'awaiting_upload' then
    return jsonb_build_object('receipt_id', r.id, 'status', r.status, 'job', public.si_job(r.id),
      'poll_after_ms', case when r.status in ('queued','processing') then 2000 else null end);
  end if;
  if p_retry and r.status <> 'failed' then raise exception 'invalid_state'; end if;
  if not p_retry and (p_sha is null or p_pages is null) then raise exception 'invalid_request'; end if;
  select coalesce(max(run_number),0)+1 into run from public.processing_jobs where receipt_id = p_id;
  if run > 3 then raise exception 'quota_exceeded'; end if;
  insert into public.processing_jobs(receipt_id,user_id,request_key,run_number)
    values(p_id,p_actor,p_key,run) returning * into j;
  insert into public.task_outbox(receipt_id,user_id,job_id,event_type,task_name)
    values(p_id,p_actor,j.id,'process_receipt','process-'||j.id::text);
  update public.receipts set status='queued', uploaded_at=coalesce(uploaded_at,now()),
    file_sha256=coalesce(file_sha256,p_sha), page_count=coalesce(page_count,p_pages) where id=p_id;
  return jsonb_build_object('receipt_id',p_id,'status','queued','job',public.si_job(p_id),'poll_after_ms',2000);
end;
$$;

commit;
