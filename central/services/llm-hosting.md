# LLM Hosting (Grove) — status & setup

## How it works (one screen)
Central sells managed LLM inference. Grove runs the models on our GPUs and mints
API keys; Central records the entitlement, registers the team owner on Grove as a
Free user, and delivers keys. There is no billing plan: LLM Hosting is prepaid at
Grove, and Central does not bill it yet. Central is never in the request path — the
caller hits `{gateway_url}/v1/chat/completions` directly. Two ways to consume:

- **On-site:** enable AI on a site → its Grove key is delivered to the site, so
  Builder/Studio work out of the box.
- **API keys:** generate a team-level key in Central → use our models from any app.

## Who does what (two cooperating authorities)
- **Central** owns entitlement, key issuance, delivery, and billing.
- **The bench (Pilot)** owns "these are my sites" and drives per-site enable —
  Central does not scan VMs, so the bench is authoritative for its site list.

| Action | Where | Surface |
|---|---|---|
| Activate LLM for the team (no plan or subscription needed) | Central console | `dashboard.activate_service` |
| Enable / disable AI on a **site** | Bench (Pilot) admin UI | `pilot.enable` / `pilot.disable` → Central mints |
| Deliver a site's key to the running site | Bench (Pilot) | `pilot.get_config` |
| Generate / reveal / revoke **team API keys** | Central console | `dashboard.generate_api_key` / `reveal_api_key` / `revoke_api_key` |
| See requests and cost, in total, per model and per day | Central console | `dashboard.get_usage` |

**Pilot → Central contract** (POST, `X-Pilot-Token` auth; team resolved from the
credential; ownership is team-scoped by the stored credential, not a site mirror):
- `pilot.enable(site, service)` — requires the team to have activated the service;
  mints/reuses the key → `{service, gateway_url, api_key, status}`.
- `pilot.disable(site, service)` — revokes the key → `{site, status}`.
- `pilot.get_config(site, service)` — delivers `{service, gateway_url, api_key}`.

## Ahead
- **Pilot PR (separate repo):** the bench admin UI that lists local sites and calls
  `pilot.enable` / `disable` / `get_config`.
- **Billing:** Central registers each Grove user as Free and does not bill LLM usage yet.

## Grove contract
Central calls these `grove.api` methods. All but the first run as the enrolled control
user, which holds Grove's `Grove Control` role.

| Method | Central sends | Central reads |
|---|---|---|
| `create_control_client` | `email`, `token` (the bootstrap secret) | `api_key`, `api_secret` |
| `provision_user` | `name`, `email`, `free` (always true) | nothing |
| `provision_key` | `email`, `title` | `gateway_url`, `api_key` |
| `revoke_key` | `api_key` | nothing |
| `available_models` | `email` | `name`, `modality`, `dialects` (`openai`, `anthropic`) |
| `usage` | `users`, `period` or `from_date` + `to_date`, `key_hash` (sha256 of one team key, optional) | `from_date`, `to_date`, `as_of`, `model_summary`, `daily_summary`, `<email>.requests`, `<email>.cost` |
| `add_credit` (operator only, not used by any screen) | `email`, `amount` (USD), `reference` | `balance` |

## Production setup

### Billing engineer (catalog)
Nothing to set up. LLM Hosting needs no Plan and no subscription.

### Operator — Central
1. Seed the `Add-on Service`: `service_key=llm`, `title="AI Inference"`,
   `handler_key=grove`, `plan_category="AI Tokens"`.
2. Register a `Service Backend` (service=`llm`, base_url=Grove URL) → **Enroll**
   (paste Grove's bootstrap secret).
3. Grant `service:view` / `service:manage` capabilities to the right roles.

### Operator — Grove
1. Deploy Grove with a **Model Deployment** (GPU) so models publish and
   `Grove Settings → Gateway Host` is set. (Without it, key provisioning fails
   with "Gateway Host is not found".)
2. `bench --site <grove> set-config control_secret <secret>` +
   `clear-cache`.
3. Tick **Is Default** on one **Model Group**. Each new Grove user starts in it, and a
   team can call no model without it. The `Grove Control` role ships with Grove.

### End-to-end check
Team activates LLM in Central → generates an API key in Central → caller hits
`{gateway_url}/v1/chat/completions` → the requests show on the **Usage** tab within
the hour.
