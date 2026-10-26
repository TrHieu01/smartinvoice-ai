// Own secret authentication allows API nudges and Vault-backed Cron calls.
const env = (name: string) => Deno.env.get(name) ?? "";
const base = env("SUPABASE_URL");
const key = env("SUPABASE_SERVICE_ROLE_KEY");
const endpoint = env("RUNPOD_ENDPOINT_ID");
// Reuse the existing endpoint-scoped Qwen key; never fall back to the CPU key.
const podKey = env("RUNPOD_VLM_TRIAL_API_KEY");
const secret = env("DISPATCHER_SECRET");

async function authenticated(value: string) {
  if (!secret || !value) return false;
  const hash = async (s: string) => new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
  const [a, b] = await Promise.all([hash(secret), hash(value)]);
  let delta = 0;
  for (let i = 0; i < a.length; i++) delta |= a[i] ^ b[i];
  return delta === 0;
}

async function rpc(name: string, data: Record<string, unknown> = {}) {
  const response = await fetch(`${base}/rest/v1/rpc/${name}`, {
    method: "POST", headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(data), signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error("database_unavailable");
  return response.json();
}

async function runpod(path: string, data?: object) {
  const response = await fetch(`https://api.runpod.ai/v2/${endpoint}/${path}`, {
    method: data ? "POST" : "GET", headers: { Authorization: `Bearer ${podKey}`, "Content-Type": "application/json" },
    body: data ? JSON.stringify(data) : undefined, signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error("provider_unavailable");
  return response.json();
}

Deno.serve(async (req) => {
  if (!await authenticated(req.headers.get("x-dispatch-secret") ?? "")) return new Response("Unauthorized", { status: 401 });
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
  if (!endpoint || !podKey || !base || !key) return new Response("Worker not configured", { status: 503 });
  let handled = 0;
  try {
    // Bounded work per invocation; durable rows remain for the next minute.
    for (let i = 0; i < 2; i++) {
      const event = await rpc("si_dispatch_claim");
      if (!event) break;
      const args = { p_id: event.id, p_token: event.dispatch_lease_token };
      try {
        if (event.event_type === "cleanup_receipt") {
          const removed = await fetch(`${base}/storage/v1/object/receipts`, {
            method: "DELETE", headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
            body: JSON.stringify({ prefixes: [event.storage_path] }), signal: AbortSignal.timeout(8000),
          });
          if (!removed.ok) throw new Error("cleanup_failed");
          await rpc("si_purge", args);
        } else if (event.provider_request_id) {
          const state = await runpod(`status/${encodeURIComponent(event.provider_request_id)}`);
          if (["IN_QUEUE", "IN_PROGRESS"].includes(state.status)) {
            await rpc("si_dispatch_ack", { ...args, p_provider: event.provider_request_id });
          } else {
            // Completion with a DB result is ignored by claim; this recovers provider crashes.
            await rpc("si_dispatch_retry", { ...args, p_code: "provider_terminal_without_result" });
          }
        } else {
          const accepted = await runpod("run", { input: { job_id: event.job_id },
            policy: { executionTimeout: 300000, ttl: 600000 } });
          if (typeof accepted.id !== "string") throw new Error("provider_invalid_response");
          await rpc("si_dispatch_ack", { ...args, p_provider: accepted.id });
        }
        handled++;
      } catch {
        await rpc("si_dispatch_retry", { ...args, p_code: "dispatch_failed" });
      }
    }
    return Response.json({ handled });
  } catch {
    return Response.json({ error: "dispatch_unavailable" }, { status: 503 });
  }
});
