/** Execute the migration against real PostgreSQL in WASM.
 * Auth and Storage tables below are minimal fixtures, not Supabase services.
 * This checks SQL/RLS/constraints, not Storage HTTP or concurrent connections.
 */
import { PGlite } from '@electric-sql/pglite';
import { readFile, readdir } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const USER_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const USER_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const hash = 'a'.repeat(64);

test('SmartInvoice migration and access invariants', async (t) => {
  const db = new PGlite();
  await db.exec(`
    create role anon;
    create role authenticated;
    create role service_role bypassrls;
    create schema auth;
    create table auth.users (id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
    $$;
    grant usage on schema public, auth to anon, authenticated, service_role;
    grant execute on function auth.uid() to anon, authenticated, service_role;
    create schema storage;
    create table storage.buckets (
      id text primary key, name text, public boolean, file_size_limit bigint,
      allowed_mime_types text[]
    );
    create table storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text, name text);
    alter table storage.objects enable row level security;
    grant usage on schema storage to anon, authenticated, service_role;
    grant select, insert, update, delete on storage.objects to authenticated, service_role;
    insert into auth.users values ('${USER_A}'), ('${USER_B}');
  `);
  const migrationDir = new URL('../supabase/migrations/', import.meta.url);
  for (const name of (await readdir(migrationDir)).filter(n => n.endsWith('.sql')).sort()) {
    // pg_cron/pg_net background workers require hosted Postgres; checked there.
    // All application schema, RPC and RLS migrations still execute in PGlite.
    if (name.endsWith('_dispatcher_extensions.sql')) continue;
    await db.exec(await readFile(new URL(name, migrationDir), 'utf8'));
  }

  async function receipt(user = USER_A) {
    const id = randomUUID();
    const path = `${user}/${id}/original.png`;
    await db.query(`insert into public.receipts
      (id,user_id,creation_key,creation_payload_hash,filename,content_type,size_bytes,
        file_extension,storage_path,upload_expires_at)
      values ($1,$2,$3,$4,'sample.png','image/png',100,'png',$5,now()+interval '2 hours')`,
      [id, user, randomUUID(), hash, path]);
    return { id, user, path };
  }

  async function asUser(user, sql, params = [], role = 'authenticated') {
    return db.transaction(async tx => {
      assert.ok(['authenticated', 'anon'].includes(role));
      await tx.exec(`set local role ${role}`);
      await tx.query("select set_config('request.jwt.claim.sub', $1, true)", [user ?? '']);
      return tx.query(sql, params);
    });
  }

  async function extractedReceipt() {
    const r = await receipt();
    const job = randomUUID();
    const result = randomUUID();
    await db.query(`update receipts set status='queued', uploaded_at=now(), file_sha256=$2,
      page_count=1 where id=$1`, [r.id, hash]);
    await db.query(`insert into processing_jobs(id,receipt_id,user_id,request_key,run_number)
      values($1,$2,$3,$4,1)`, [job, r.id, r.user, randomUUID()]);
    await db.query(`update processing_jobs set status='running',attempts=1,lease_token=$2,
      lease_expires_at=now()+interval '360 seconds' where id=$1`, [job, randomUUID()]);
    await db.query("update receipts set status='processing' where id=$1", [r.id]);
    await db.query(`insert into extraction_results(id,receipt_id,user_id,job_id,schema_version,
      pipeline_version,raw_ocr_json,extracted_json,evidence,warnings,timings,processed_at)
      values($1,$2,$3,$4,'1.0.0','sql-fixture','{}','{}','[]','[]','{}',now())`,
      [result, r.id, r.user, job]);
    await db.query(`update receipts set status='needs_review',current_extraction_id=$2,
      merchant='Sample',purchase_date='2026-10-21',total_amount=100,currency='VND' where id=$1`,
      [r.id, result]);
    await db.query(`update processing_jobs set status='succeeded',lease_token=null,
      lease_expires_at=null,finished_at=now() where id=$1`, [job]);
    return { ...r, job, result };
  }

  await t.test('RLS isolates tenants and anonymous access', async () => {
    const a = await receipt();
    const b = await receipt(USER_B);
    const visible = await asUser(USER_A, 'select id from receipts where id in ($1,$2)', [a.id,b.id]);
    assert.deepEqual(visible.rows.map(x => x.id), [a.id]);
    await assert.rejects(asUser(null, 'select * from receipts', [], 'anon'), /permission denied/);
    assert.equal((await asUser(USER_B, 'select * from receipts where id=$1', [a.id])).rows.length, 0);
  });

  await t.test('authenticated users cannot forge data or read internal tables', async () => {
    const a = await receipt();
    await assert.rejects(asUser(USER_A, "update receipts set merchant='forged' where id=$1", [a.id]), /permission denied/);
    for (const name of ['processing_jobs','extraction_results','task_outbox']) {
      await assert.rejects(asUser(USER_A, `select * from ${name}`), /permission denied/);
    }
  });

  await t.test('composite foreign keys prevent cross-tenant item attachment', async () => {
    const a = await receipt();
    await assert.rejects(db.query(`insert into receipt_items(receipt_id,user_id,line_number,name)
      values($1,$2,1,'Bad item')`, [a.id, USER_B]), /foreign key/);
  });

  await t.test('only one active job per receipt and one job per request key', async () => {
    const a = await receipt();
    const key = randomUUID();
    await db.query(`insert into processing_jobs(receipt_id,user_id,request_key,run_number)
      values($1,$2,$3,1)`, [a.id, a.user, key]);
    await assert.rejects(db.query(`insert into processing_jobs(receipt_id,user_id,request_key,run_number)
      values($1,$2,$3,2)`, [a.id,a.user,randomUUID()]), /processing_jobs_one_active_idx/);
    await assert.rejects(db.query(`insert into processing_jobs(receipt_id,user_id,request_key,run_number)
      values($1,$2,$3,3)`, [a.id,a.user,key]), /duplicate key/);
  });

  await t.test('receipt identity, states, finite amounts and version compare-and-swap', async () => {
    const a = await receipt();
    await assert.rejects(db.query('update receipts set user_id=$2 where id=$1', [a.id,USER_B]), /immutable_receipt_identity/);
    await assert.rejects(db.query("update receipts set status='confirmed' where id=$1", [a.id]), /invalid_receipt_transition/);
    await assert.rejects(db.query("update receipts set total_amount='NaN' where id=$1", [a.id]), /check constraint/);
    const first = await db.query("update receipts set merchant='A' where id=$1 and version=1 returning version", [a.id]);
    const stale = await db.query("update receipts set merchant='B' where id=$1 and version=1 returning version", [a.id]);
    assert.equal(first.rows[0].version, 2);
    assert.equal(stale.rows.length, 0);
  });

  await t.test('fencing token prevents an old attempt from committing a job', async () => {
    const a = await receipt();
    const job = randomUUID(), oldToken = randomUUID(), newToken = randomUUID();
    await db.query(`insert into processing_jobs(id,receipt_id,user_id,request_key,run_number,status,
      attempts,lease_token,lease_expires_at) values($1,$2,$3,$4,1,'running',1,$5,now()-interval '1 second')`,
      [job,a.id,a.user,randomUUID(),oldToken]);
    await db.query(`update processing_jobs set lease_token=$2,attempts=attempts+1,
      lease_expires_at=now()+interval '360 seconds' where id=$1 and lease_expires_at < now()`, [job,newToken]);
    const stale = await db.query(`update processing_jobs set status='succeeded',lease_token=null,
      lease_expires_at=null,finished_at=now() where id=$1 and lease_token=$2
      and lease_expires_at > now() returning id`, [job,oldToken]);
    assert.equal(stale.rows.length, 0);
  });

  await t.test('AI results and correction history reject updates', async () => {
    const r = await extractedReceipt();
    await assert.rejects(db.query("update extraction_results set pipeline_version='changed' where id=$1", [r.result]), /history_is_append_only/);
    const correction = randomUUID();
    await db.query(`insert into receipt_corrections(id,receipt_id,user_id,base_extraction_id,
      from_version,to_version,action,before_data,after_data,changed_fields)
      values($1,$2,$3,$4,4,5,'confirm','{}','{}','[]')`, [correction,r.id,r.user,r.result]);
    await assert.rejects(db.query("update receipt_corrections set after_data='{}' where id=$1", [correction]), /history_is_append_only/);
  });

  await t.test('deletion hides parent, items, history and private storage immediately', async () => {
    const r = await extractedReceipt();
    await db.query("insert into receipt_items(receipt_id,user_id,line_number,name) values($1,$2,1,'Sample')", [r.id,r.user]);
    await db.query("insert into storage.objects(bucket_id,name) values('receipts',$1)", [r.path]);
    assert.equal((await asUser(r.user, 'select * from storage.objects where name=$1', [r.path])).rows.length, 1);
    await db.query("update receipts set status='deleting',deleted_at=now() where id=$1", [r.id]);
    for (const [sql, params] of [
      ['select * from receipts where id=$1',[r.id]],
      ['select * from receipt_items where receipt_id=$1',[r.id]],
      ['select * from storage.objects where name=$1',[r.path]],
    ]) {
      assert.equal((await asUser(r.user, sql, params)).rows.length, 0);
    }
    await assert.rejects(db.query("update receipts set status='needs_review' where id=$1", [r.id]), /invalid_receipt_transition/);
    await db.query('delete from receipts where id=$1', [r.id]);
    assert.equal((await db.query('select * from extraction_results where receipt_id=$1', [r.id])).rows.length, 0);
  });

  await t.test('bucket enforces 5 MB and explicit MIME allowlist, without client upload policy', async () => {
    const bucket = (await db.query("select * from storage.buckets where id='receipts'")).rows[0];
    assert.equal(Number(bucket.file_size_limit), 5_000_000);
    assert.equal(bucket.public, false);
    assert.deepEqual(bucket.allowed_mime_types.sort(), ['application/pdf','image/jpeg','image/png','image/webp']);
    await assert.rejects(asUser(USER_A, "insert into storage.objects(bucket_id,name) values('receipts','bad')"), /row-level security/);
  });

  await t.test('upload ticket expiry can only grow while still awaiting upload', async () => {
    const r = await receipt();
    await db.query("update receipts set upload_expires_at=upload_expires_at+interval '1 hour' where id=$1", [r.id]);
    await assert.rejects(db.query("update receipts set upload_expires_at=now() where id=$1", [r.id]), /invalid_upload_ticket_extension/);
    await db.query("update receipts set status='queued',uploaded_at=now(),page_count=1,file_sha256=$2 where id=$1", [r.id,hash]);
    await assert.rejects(db.query("update receipts set upload_expires_at=upload_expires_at+interval '1 hour' where id=$1", [r.id]), /invalid_upload_ticket_extension/);
  });

  await t.test('outbox rejects duplicate cleanup intents and half-defined dispatch leases', async () => {
    const r = await receipt();
    await db.query(`insert into task_outbox(receipt_id,user_id,event_type,task_name)
      values($1,$2,'cleanup_receipt',$3)`, [r.id,r.user,`cleanup-${r.id}`]);
    await assert.rejects(db.query(`insert into task_outbox(receipt_id,user_id,event_type,task_name)
      values($1,$2,'cleanup_receipt',$3)`, [r.id,r.user,`duplicate-${r.id}`]), /task_outbox_cleanup_once_idx/);
    await assert.rejects(db.query("update task_outbox set dispatch_lease_token=$2 where receipt_id=$1", [r.id,randomUUID()]), /outbox_dispatch_lease/);
  });

  await t.test('transaction commands cover create, leases, extraction, correction, analytics and deletion', async () => {
    async function rpc(name, args) {
      const values = Object.values(args);
      const params = Object.keys(args).map((key, index) => `${key} => $${index + 1}`).join(',');
      return (await db.query(`select public.${name}(${params}) value`, values)).rows[0].value;
    }
    const key = randomUUID();
    const args = {p_actor:USER_B,p_key:key,p_filename:'receipt.pdf',p_mime:'application/pdf',p_size:123,p_hash:hash};
    const r = await rpc('si_create', args);
    assert.equal(r.status, 'awaiting_upload');
    assert.equal((await rpc('si_create',args)).id,r.id);
    await assert.rejects(rpc('si_create',{...args,p_hash:'b'.repeat(64)}),/idempotency_conflict/);
    await assert.rejects(rpc('si_detail',{p_actor:USER_A,p_id:r.id}),/receipt_not_found/);
    await assert.rejects(asUser(USER_B,'select si_detail($1,$2)',[USER_B,r.id]),/permission denied for function/);
    const queued = await rpc('si_enqueue',{p_actor:USER_B,p_id:r.id,p_key:randomUUID(),p_sha:hash,p_pages:1});
    const duplicate = await rpc('si_enqueue',{p_actor:USER_B,p_id:r.id,p_key:randomUUID(),p_sha:hash,p_pages:1});
    assert.equal(duplicate.job.id,queued.job.id);
    const job = queued.job.id;
    const lease = await rpc('si_claim',{p_job:job});
    assert.equal(lease.decision,'claimed');
    assert.equal((await rpc('si_claim',{p_job:job})).decision,'busy');
    const fixture = JSON.parse(await readFile(new URL('../contracts/examples/extraction.vi.json',import.meta.url),'utf8'));
    fixture.receipt_id=r.id; fixture.job_id=job;
    fixture.schema_version='1.1.0';
    fixture.data.merchant_address='12 Test Street';
    fixture.data.payment_method='Cash';
    fixture.data.items=[{line_number:1,name:'Sample',unit:'kg',quantity:'1',unit_price:'100',line_total:'100'}];
    for (const token of [null,randomUUID()]) {
      assert.equal(await rpc('si_complete',{p_job:job,p_token:token,p_result:fixture}),false);
      assert.equal(await rpc('si_fail',{p_job:job,p_token:token,p_code:'invalid'}),false);
    }
    assert.equal(await rpc('si_complete',{p_job:job,p_token:lease.lease_token,p_result:fixture}),true);
    assert.equal(await rpc('si_complete',{p_job:job,p_token:lease.lease_token,p_result:fixture}),false);
    const detail = await rpc('si_detail',{p_actor:USER_B,p_id:r.id});
    assert.equal(detail.status,'needs_review');
    assert.equal(detail.data.merchant_address,'12 Test Street');
    assert.equal(detail.data.payment_method,'Cash');
    assert.equal(detail.data.items[0].unit,'kg');
    const before = await rpc('si_analytics',{p_actor:USER_B,p_from:'2026-01-01',p_to:'2026-12-31'});
    const changed = {...detail.data,merchant:'Reviewed Merchant',merchant_address:'34 Reviewed Street',payment_method:'Card',items:detail.data.items.map(i=>({...i,unit:'bag'})),purchase_date:'2026-10-21',total_amount:'123456.00',currency:'VND'};
    const reviewed = await rpc('si_review',{p_actor:USER_B,p_id:r.id,p_expected:detail.version,p_action:'confirm',p_data:changed,p_category:'food',p_warnings:[]});
    assert.equal(reviewed.status,'confirmed');
    assert.equal(reviewed.latest_extraction.data.merchant,fixture.data.merchant);
    assert.equal(reviewed.data.merchant_address,'34 Reviewed Street');
    assert.equal(reviewed.data.payment_method,'Card');
    assert.equal(reviewed.data.items[0].unit,'bag');
    assert.equal(reviewed.latest_extraction.data.items[0].unit,'kg');
    await assert.rejects(rpc('si_review',{p_actor:USER_B,p_id:r.id,p_expected:detail.version,p_action:'confirm',p_data:changed,p_category:'food',p_warnings:[]}),/version_conflict/);
    const after = await rpc('si_analytics',{p_actor:USER_B,p_from:'2026-01-01',p_to:'2026-12-31'});
    assert.equal(Number(after.total_amount)-Number(before.total_amount),123456);
    const filtered = await rpc('si_list',{p_actor:USER_B,p_merchant:'reviewed merchant'});
    assert.equal(filtered.items[0].id,r.id);
    await rpc('si_delete',{p_actor:USER_B,p_id:r.id});
    await assert.rejects(rpc('si_detail',{p_actor:USER_B,p_id:r.id}),/receipt_not_found/);
    assert.equal((await rpc('si_delete',{p_actor:USER_B,p_id:r.id})).status,'deleting');
  });

  await t.test('dispatcher leases and retry budget bound provider sends', async () => {
    await db.exec("update task_outbox set available_at=now()+interval '1 day' where status in ('pending','published')");
    const r = await receipt(USER_B);
    const invoke = async (name, values, placeholders) => (await db.query(`select public.${name}(${placeholders}) value`,values)).rows[0].value;
    let queued = await invoke('si_enqueue',[USER_B,r.id,randomUUID(),hash,1],'$1,$2,$3,$4,$5');
    const originalKey = (await db.query('select request_key from processing_jobs where id=$1',[queued.job.id])).rows[0].request_key;
    for (let run=1;run<=3;run++) {
      if (run>1) queued = await invoke('si_enqueue',[USER_B,r.id,randomUUID(),true],'p_actor=>$1,p_id=>$2,p_key=>$3,p_retry=>$4');
      for (let attempt=1;attempt<=3;attempt++) {
        await db.query("update task_outbox set available_at=now()-interval '1 second' where job_id=$1",[queued.job.id]);
        const event = await invoke('si_dispatch_claim',[],'');
        assert.equal(event.job_id,queued.job.id);
        assert.equal(event.dispatch_attempts,attempt);
        assert.equal(await invoke('si_dispatch_claim',[],''),null);
        assert.equal(await invoke('si_dispatch_ack',[event.id,null,'forged'],'$1,$2,$3'),false);
        if (attempt===1) {
          await invoke('si_dispatch_ack',[event.id,event.dispatch_lease_token,'provider-id'],'$1,$2,$3');
          await db.query("update task_outbox set available_at=now()-interval '1 second' where id=$1",[event.id]);
          const polling = await invoke('si_dispatch_claim',[],'');
          assert.equal(polling.provider_request_id,'provider-id');
          assert.equal(polling.dispatch_attempts,1);
          event.dispatch_lease_token=polling.dispatch_lease_token;
        }
        await invoke('si_dispatch_retry',[event.id,event.dispatch_lease_token,'provider_failed'],'$1,$2,$3');
      }
      assert.equal((await db.query('select status from receipts where id=$1',[r.id])).rows[0].status,'failed');
    }
    await assert.rejects(invoke('si_enqueue',[USER_B,r.id,randomUUID(),true],'p_actor=>$1,p_id=>$2,p_key=>$3,p_retry=>$4'),/quota_exceeded/);
    const replay = await invoke('si_enqueue',[USER_B,r.id,originalKey,hash,1],'$1,$2,$3,$4,$5');
    assert.equal(replay.job.run_number,1);
  });

  await db.close();
});
