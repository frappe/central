# LLM Hosting (Grove) — status & setup

## How it works (one screen)
Central sells managed LLM inference. Grove runs the models on our GPUs and mints
API keys; Central records the entitlement, delivers keys, and meters usage onto
the team's AI-Tokens bill. Two ways to consume, one meter:
- **On-site:** enable AI per site → key delivered to the site.
- **API keys:** generate a team key → use our models from any app.

## Ahead
- Site delivery wiring (site → Pilot → `get_config`) — deferred; being added
  separately.
- Per-site enable to also live in the bench management UI.
- Grove ships its `Central Control` role + permissions (Grove dev).

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
Team subscribes to an AI-Tokens plan (Billing) → activates LLM → enables a site
or generates an API key → calls `{gateway_url}/v1/chat/completions` → usage
appears on the next hourly reconciliation and on the team's invoice.
