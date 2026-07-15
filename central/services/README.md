# Managed Add-on Services

Central's control plane for team add-ons (LLM Hosting via Grove today; Object Storage
via Satellite later). Central owns catalogue, entitlement, per-site credentials, and
billing links; the executor (Grove) owns the runtime and mints the credentials.

## Setting up LLM Hosting (Grove)

### 1. Install Grove on a Grove site (per deployment)

```
bench install-app <grove-site> grove
```

If the install fails with `cannot import name 'ansible_runner'`, fix
`proxy_server.py` to import `ansible_runner` from `grove`, not `grove.provision`
(already fixed in this bench). Remove any orphan `Module Def "Grove"` before retrying.

### 2. Set the bootstrap secret on Grove

This is the one manual trust seed. Pick a strong random value.

```
bench --site <grove-site> set-config control_bootstrap_secret <random-secret>
bench --site <grove-site> clear-cache      # required: the running worker caches config at boot
```

### 3. Seed the service catalogue in Central (one-time)

Create one `Add-on Service` row (Desk → Add-on Service → New, or CLI):

```
frappe-cli doc create "Add-on Service" \
  --set service_key=llm --set title="LLM Hosting" \
  --set handler_key=grove --set plan_category="AI Tokens"
```

### 4. Register the Grove backend (Desk button)

Desk → **Service Backend** → New:

1. Set **Service** = `llm` and **Base URL** = the Grove site URL, then **Save**.
2. Click **Enroll**, paste the bootstrap secret from step 2.

Central calls Grove's `enroll_control_client`, which mints a dedicated
`central-control` user + `Central Control` role + API key on Grove; Central stores the
credential (write-only) and marks the backend **Active**. Re-clicking **Rotate
Credential** issues a fresh key. The bootstrap secret is never stored in Central.

### 5. Models and plan policy

- On Grove, publish models (a `Model` becomes published once it has an active
  `Model Deployment` on an inference server).
- In Central, `central.services.llm.sync_models` (daily job, or run manually) imports
  the published models into `LLM Model`; set each one's **Tier** (Fast/Balanced/Premium).
- Create an `LLM Plan Policy` per LLM plan and list its **Allowed Tiers**. A plan with
  no policy grants all published models.

### 6. Activate for a team and enable sites (API today)

```
central.services.api.dashboard.activate_service(team, "llm")     # needs an active AI Tokens subscription
central.services.api.dashboard.enable_site(managed_service, site) # mints the site's Grove key
```

The site then pulls `{gateway_url, api_key}` via
`central.services.api.pilot.get_config(site, "llm")` and calls the gateway directly.
Hourly, `central.services.llm.pull_usage` reconciles Grove's token usage into billing.

## Gotchas

- Always `clear-cache` on Grove after `set-config` for a config change to take effect.
- Grove returns no models until a `Model Deployment` exists.
- `get_config` over the real site→Pilot path needs the Pilot proxy allowlist (pending).
