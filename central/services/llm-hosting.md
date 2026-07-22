# LLM Hosting (Grove) — status & setup

## How it works (one screen)
Central sells managed LLM inference. Grove runs the models on our GPUs and mints
API keys; Central records the entitlement, delivers keys, and meters usage onto
the team's AI-Tokens bill. Central is never in the request path — the caller hits
`{gateway_url}/v1/chat/completions` directly. Two ways to consume, one meter:

- **On-site:** enable AI on a site → its Grove key is delivered to the site, so
  Builder/Studio work out of the box.
- **API keys:** generate a team-level key in Central → use our models from any app.

## Who does what (two cooperating authorities)
- **Central** owns entitlement, key issuance, delivery, and billing.
- **The bench (Pilot)** owns "these are my sites" and drives per-site enable —
  Central does not scan VMs, so the bench is authoritative for its site list.

| Action | Where | Surface |
|---|---|---|
| Activate LLM for the team (needs an AI-Tokens subscription) | Central console | `dashboard.activate_service` |
| Enable / disable AI on a **site** | Bench (Pilot) admin UI | `pilot.enable` / `pilot.disable` → Central mints |
| Deliver a site's key to the running site | Bench (Pilot) | `pilot.get_config` |
| Generate / reveal / revoke **team API keys** | Central console | `dashboard.generate_api_key` / `reveal_api_key` / `revoke_api_key` |
| Meter usage → team `Tokens` bill | Central (hourly) | `llm.pull_usage` (site keys **and** API keys) |

**Pilot → Central contract** (POST, `X-Pilot-Token` auth; team resolved from the
credential; ownership is team-scoped by the stored credential, not a site mirror):
- `pilot.enable(site, service)` — requires the team to have activated the service;
  mints/reuses the key → `{service, gateway_url, api_key, status}`.
- `pilot.disable(site, service)` — revokes the key → `{site, status}`.
- `pilot.get_config(site, service)` — delivers `{service, gateway_url, api_key}`.

## Ahead
- **Pilot PR (separate repo):** the bench admin UI that lists local sites and calls
  `pilot.enable` / `disable` / `get_config`.
- **Grove:** ships its `Central Control` role + permissions so `provision_key` etc.
  run for the enrolled control user. Central only relies on `enroll_control_client`.

## Production setup

### Billing engineer (catalog)
1. `AI Tokens` Plan Category exists (seeded). Pick **settlement mode**:
   *Postpaid Overage* (recommended — meter & bill, no cap) or *Prepaid Pack*
   (hard token cap = bundled allowance).
2. Create an active **Plan** in `AI Tokens` with a `Tokens` **Plan Includes** row
   + a per-currency **Catalog Rate**. Give it a clear title (shown in the UI).

### Operator — Central
1. Seed the `Add-on Service`: `service_key=llm`, `title="LLM Hosting"`,
   `handler_key=grove`, `plan_category="AI Tokens"`.
2. Register a `Service Backend` (service=`llm`, base_url=Grove URL) → **Enroll**
   (paste Grove's bootstrap secret).
3. Grant `service:view` / `service:manage` capabilities to the right roles.
4. After Grove has models: run `central.services.llm.sync_models`, set each
   `LLM Model`'s tier, and (optional) create an `LLM Plan Policy` per plan for
   tier gating. `pull_usage` runs hourly.

### Operator — Grove
1. Deploy Grove with a **Model Deployment** (GPU) so models publish and
   `Grove Settings → Gateway Host` is set. (Without it, key provisioning fails
   with "Gateway Host is not found".)
2. `bench --site <grove> set-config control_bootstrap_secret <secret>` +
   `clear-cache`.
3. Ensure the `Central Control` role has DocPerms to create Users + API Keys and
   read Usage/Models (Grove-side).

### End-to-end check
Team subscribes to an AI-Tokens plan (Billing) → activates LLM in Central →
enables a site from the **server dashboard** (or generates an API key in Central)
→ caller hits `{gateway_url}/v1/chat/completions` → usage appears on the next
hourly reconciliation and on the team's invoice.
