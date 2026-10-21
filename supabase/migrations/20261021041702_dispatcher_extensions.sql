-- Hosted Supabase scheduler and async HTTP transport. Secrets and activation
-- are configured separately so a fresh database never sends compute jobs.
create extension if not exists pg_cron;
create extension if not exists pg_net;
