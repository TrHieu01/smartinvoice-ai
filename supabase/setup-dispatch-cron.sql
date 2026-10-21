-- Run once AFTER enabling Cron/pg_net and saving both named Vault secrets.
-- No credential literal belongs in this file or the Cron command.
do $$ begin
  if not exists(select 1 from vault.decrypted_secrets where name='smartinvoice_dispatch_url')
    or not exists(select 1 from vault.decrypted_secrets where name='smartinvoice_dispatch_secret') then
    raise exception 'Configure dispatcher Vault secrets first';
  end if;
  if exists(select 1 from cron.job where jobname='smartinvoice-dispatch') then
    raise exception 'Cron already exists; inspect before changing';
  end if;
end $$;
select cron.schedule('smartinvoice-dispatch', '* * * * *', $cron$
  select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name='smartinvoice_dispatch_url' limit 1),
    headers := jsonb_build_object('Content-Type','application/json','x-dispatch-secret',
      (select decrypted_secret from vault.decrypted_secrets where name='smartinvoice_dispatch_secret' limit 1)),
    body := '{}'::jsonb, timeout_milliseconds := 30000
  );
$cron$);
