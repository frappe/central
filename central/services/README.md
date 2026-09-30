# Managed Add-on Services

Central's control plane for team add-ons (LLM Hosting via Grove today; Object Storage
via Satellite later). Central owns catalogue, entitlement, per-site credentials, and
billing links; the executor (Grove) owns the runtime and mints the credentials.

## Current DocTypes

| DocType | What it records | Billing relationship |
| --- | --- | --- |
| **Add-on Service** | A service offered by Central, such as `llm`. | Links the service to the Plan Category that pays for it. |
| **Service Backend** | An enrolled provider endpoint and Central's control credential. | None; it is runtime configuration. |
| **Managed Service** | A team's activated add-on and the subscription that entitles it. For LLM Hosting, `provider_ref` is the team's Grove user. | Requires an active subscription in the service's Plan Category. LLM Hosting needs none. |
| **Service Credential** | A provider credential under a managed service, either per-`Site` (bench-delivered) or a team-level API key (`Team`, with a `label`), set by `subject_type`. | Provider usage is grouped through active credentials of both subject types and reported to Billing. |

## LLM Hosting and the Grove user

Each team has one Grove user: the email of the team owner when the team activates LLM Hosting. Central registers it on Grove (`grove.api.provision_user`) and keeps it in `Managed Service.provider_ref`. Team members get no Grove user.

- A team API key is a key of that Grove user. The key title on Grove is the key label.
- Central registers the Grove user as **Free**. Grove records the usage and its cost for a Free user, and it does not charge or block the user. Central does not bill LLM usage yet.
- Grove decides which models the Grove user can call: each new Grove user starts in Grove's default **Model Group**. Central does not send the models of the plan or a token limit. The AI page shows the models that Grove reports, or "No models accessible yet."
- The **Usage** tab of the AI page shows the requests and the cost that Grove reports for a period, in total, for each model, and for each day (`central.services.api.dashboard.get_usage`). The cost is what Grove charged, so it is 0 while the Grove user is Free.
- A transfer of team ownership does not change the Grove user.
- One Grove user serves one team. An owner of 2 teams can activate LLM Hosting for one of them only.
- An operator can add credit to the Grove user, in USD, with `central.services.api.dashboard.add_credit(managed_service, amount, reference)`. No screen calls it, and it charges the team nothing. Credit has no effect on a Free user.

## Billing for LLM Hosting

LLM Hosting needs no billing Plan and no subscription. It is prepaid at Grove, and how a team pays for that credit is not decided yet. A team with `service:manage` activates it directly.

Central keeps no model catalogue and no plan policy for LLM Hosting: Grove decides the models, and Central sends it no model list and no token limit. `Add-on Service.plan_category` is a mandatory field, so the `llm` row still names a category.

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
bench --site <grove-site> set-config control_secret <random-secret>
bench --site <grove-site> clear-cache      # required: the running worker caches config at boot
```

### 3. Seed the service catalogue in Central (one-time)

Create one `Add-on Service` row (Desk → Add-on Service → New, or CLI):

```
frappe-cli doc create "Add-on Service" \
  --set service_key=llm --set title="AI Inference" \
  --set handler_key=grove --set plan_category="AI Tokens"
```

### 4. Register the Grove backend (Desk button)

Desk → **Service Backend** → New:

1. Set **Service** = `llm` and **Base URL** = the Grove site URL, then **Save**.
2. Click **Enroll**, paste the bootstrap secret from step 2.

Central calls Grove's `grove.api.create_control_client` with the bootstrap secret and the email `central@<central-site>`. Grove creates that user with the `Grove Control` role and returns its API key. Central stores the credential (write-only) and marks the backend **Active**. The bootstrap secret is never stored in Central.

Grove enrolls one email one time. **Rotate Credential** enrolls again, so Grove refuses it until the `central@<central-site>` user is deleted on Grove.

### 5. Models

On Grove, publish models and tick **Is Default** on one `Model Group` that lists them. Central has nothing to set up.

### 6. Activate for a team and enable sites (API today)

```
central.services.api.dashboard.activate_service(team, "llm")     # registers the team owner as a Free Grove user
central.services.api.dashboard.enable_site(managed_service, site) # mints the site's Grove key
```

The site then pulls `{gateway_url, api_key}` via
`central.services.api.pilot.get_config(site, "llm")` and calls the gateway directly.
Hourly, `central.services.llm.pull_usage` reconciles Grove's token usage into billing.

## Gotchas

- Always `clear-cache` on Grove after `set-config` for a config change to take effect.
- Grove returns no models until a `Model Deployment` exists.
- `get_config` over the real site→Pilot path needs the Pilot proxy allowlist (pending).
