# Managed Add-on Services

Central's control plane for team add-ons (LLM Hosting via Grove today; Object Storage
via Satellite later). Central owns catalogue, entitlement, per-site credentials, and
billing links; the executor (Grove) owns the runtime and mints the credentials.

## Current DocTypes

| DocType | What it records | Billing relationship |
| --- | --- | --- |
| **Add-on Service** | A service offered by Central, such as `llm`. | Links the service to the Plan Category that pays for it. |
| **Service Backend** | An enrolled provider endpoint and Central's control credential. | None; it is runtime configuration. |
| **LLM Model** | A model published by Grove and its `Fast`, `Balanced`, or `Premium` tier. | Its tier is what a plan policy permits. |
| **LLM Plan Policy** | The LLM access policy for one Billing Plan. | Maps that plan to its allowed model tiers. One policy per Plan. |
| **LLM Plan Tier** | One allowed-tier row inside an LLM Plan Policy. | Not managed on its own. |
| **Managed Service** | A team's activated add-on and the subscription that entitles it. | Requires an active subscription in the service's Plan Category. |
| **Site Service Credential** | One site's provider credential and status for an active managed service. | Provider usage is grouped through active credentials and reported to Billing. |

## Billing setup for LLM Hosting

1. Create the `AI Tokens` **Plan Category** as a metered `Tokens` family. Choose:
   `Prepaid Pack` to hard-cap included tokens, or `Postpaid Overage` to bill excess.
2. Create an active **Plan** in that category with one `Plan Includes` row for
   `Tokens`, then add its **Catalog Rate**.
3. Set `Add-on Service.plan_category` to `AI Tokens`.
4. Sync published **LLM Models**, assign each a tier, and create an **LLM Plan
   Policy** for each Plan with the tiers that Plan should receive.
5. When a team activates LLM, Central uses its active subscription's Plan to set the
   permitted models. For prepaid plans it also sends the Plan Includes token quantity
   as the provider-side token limit. Usage is reconciled hourly into the `Tokens`
   meter.

**Important:** no LLM Plan Policy (or one with no tier rows) currently permits all
published models. Tier changes apply when a site is provisioned; re-enable existing
sites to apply a changed policy.

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
