begin;
create function public.si_dispatch_claim() returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare o public.task_outbox; token uuid := gen_random_uuid(); path text;
begin
  select * into o from public.task_outbox where status in ('pending','published')
    and available_at <= now() and (dispatch_lease_expires_at is null or dispatch_lease_expires_at < now())
    and (event_type='cleanup_receipt' or exists (
      select 1 from public.processing_jobs j where j.id=job_id and j.status in ('pending','running')))
    order by available_at,id for update skip locked limit 1;
  if not found then return null; end if;
  update public.task_outbox set dispatch_lease_token=token,
    dispatch_lease_expires_at=now()+interval '60 seconds',
    dispatch_attempts=dispatch_attempts+case when provider_request_id is null then 1 else 0 end
    where id=o.id returning * into o;
  select storage_path into path from public.receipts where id=o.receipt_id;
  return to_jsonb(o)||jsonb_build_object('storage_path',path);
end;
$$;

create function public.si_dispatch_ack(p_id uuid,p_token uuid,p_provider text) returns boolean
language plpgsql security invoker set search_path = '' as $$
begin
  update public.task_outbox set provider_request_id=p_provider,status='published',
    published_at=coalesce(published_at,now()),available_at=now()+interval '1 minute',
    dispatch_lease_token=null,dispatch_lease_expires_at=null,last_error_code=null
    where id=p_id and dispatch_lease_token=p_token and status<>'cancelled';
  return found;
end;
$$;

create function public.si_dispatch_retry(p_id uuid,p_token uuid,p_code text) returns boolean
language plpgsql security invoker set search_path = '' as $$
declare o public.task_outbox; j public.processing_jobs; rid uuid;
begin
  select receipt_id into rid from public.task_outbox where id=p_id;
  perform 1 from public.receipts where id=rid for update;
  select * into j from public.processing_jobs where id=(select job_id from public.task_outbox where id=p_id) for update;
  select * into o from public.task_outbox where id=p_id for update;
  if not found or o.dispatch_lease_token is distinct from p_token or o.status='cancelled' then return false; end if;
  if j.status='running' and j.lease_expires_at>now() then
    update public.task_outbox set available_at=j.lease_expires_at+interval '5 seconds',
      dispatch_lease_token=null,dispatch_lease_expires_at=null where id=p_id;
    return false;
  end if;
  if o.event_type='process_receipt' and o.dispatch_attempts>=3 then
    if j.status in ('pending','running') then
      update public.processing_jobs set status='failed',error_code=p_code,lease_token=null,
        lease_expires_at=null,finished_at=now() where id=j.id;
      update public.receipts set status='failed' where id=rid and status in ('queued','processing');
    end if;
    update public.task_outbox set status='cancelled',dispatch_lease_token=null,
      dispatch_lease_expires_at=null,last_error_code=p_code where id=p_id;
  else
    if j.status in ('pending','running') then
      update public.processing_jobs set status='pending',lease_token=null,lease_expires_at=null where id=j.id;
      update public.receipts set status='queued' where id=rid and status='processing';
    end if;
    update public.task_outbox set status='pending',provider_request_id=null,
      available_at=now()+interval '1 minute'*least(dispatch_attempts,10),last_error_code=p_code,
      dispatch_lease_token=null,dispatch_lease_expires_at=null where id=p_id;
  end if;
  return true;
end;
$$;

create function public.si_purge(p_id uuid,p_token uuid) returns boolean
language plpgsql security invoker set search_path = '' as $$
declare rid uuid;
begin
  select receipt_id into rid from public.task_outbox where id=p_id;
  perform 1 from public.receipts where id=rid and status='deleting'
    and upload_expires_at+interval '5 minutes'<=now() for update;
  if not found then return false; end if;
  perform 1 from public.task_outbox where id=p_id and event_type='cleanup_receipt'
    and dispatch_lease_token=p_token and dispatch_lease_expires_at>now() for update;
  if not found then return false; end if;
  -- Called only after the Storage API successfully removed the object.
  delete from public.receipts where id=rid;
  return true;
end;
$$;

do $$ declare f record; begin
  for f in select p.oid::regprocedure signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname like 'si\_%' escape '\' loop
    execute format('revoke all on function %s from public, anon, authenticated',f.signature);
    execute format('grant execute on function %s to service_role',f.signature);
  end loop;
end $$;
commit;
