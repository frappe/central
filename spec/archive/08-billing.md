# 08 — Billing

Billing is implemented by installing **[`press_billing`](https://github.com/saurabh6790/press_billing)**
into Central as the "billing & payments system of record for Frappe Cloud v2".
This spec is the contract for *where it sits* and *how it wires to the other two
planes* — it does not re-describe every DocType the app already ships.

> **Status:** billing is out of scope for the POC (`spec/README`). This spec
> exists so the IAM, registry, and SSO work we build *now* leaves the right
> seams, and so dropping `press_billing` in later is config, not surgery.

## First principles

1. **Billing is an account-level (global) concern → it lives in Central.**
   Money attaches to the **Team** (the ownership unit, `spec/06`), and Central is
   the only plane that owns Teams and identity. Atlas never prices, invoices, or
   holds a card. A region down must not stop a charge; a billing outage must not
   stop a running VM.

2. **Usage is regional → it is metered in Atlas and reported up.** The fact that
   `vm-9` consumed 720 vCPU-hours is a regional measurement. Atlas's agent rolls
   it up and reports it to Central, which prices it. This is the **mirror image
   of the registry**: ownership flows *down*, usage flows *up*, over a sibling of
   the same channel.

3. **Enforcement of billing standing → flows back down as a signed token.**
   Central decides "this team is `past_due`, cap its spend, forbid terminate";
   it issues an **Entitlement Token** carrying team-level standing (`suspend` /
   `terminate` caps, quotas) that Atlas honours. **Note (post-grilling):** unlike
   IAM permissions — which are per-user and ride in the OAuth token (`spec/06`) —
   billing standing is **team-level state Atlas needs even when no user is logged
   in** (e.g. a scheduled non-payment suspend). So the entitlement is *not* a
   token claim; its delivery is designed when billing is actually built (likely a
   per-team flag carried on the registry pull, `spec/07`). Out of scope now.

4. **Price is locked at provision time, not read live.** When a resource is
   created, its plan allowance + per-unit rate are frozen into a **Price Lock**.
   Bills are computed against the lock, so a public price change never silently
   re-bills existing resources. Identity-style grandfathering, for money.

So billing reuses the cross-plane patterns this architecture already has: usage
flows **up** on the registry sync transport (`spec/07`), and team-level standing
flows **down** to influence Atlas's provisioning/standing gates. The exact
down-channel is deferred with the rest of billing — the point for now is only
that the **seams** (`resource_id == registry name`, team-level standing) are left
clean so billing drops in later without surgery.

## Where it attaches

`press_billing` keys everything off **`team`** (a `Data` field holding the
Central `Team.name`). With `spec/06`'s surrogate Team key this is stable across
renames — the reason that fix matters for billing. Its DocTypes group as:

| Concern | DocTypes (from the app) |
|---|---|
| **Identity of the payer** | `Billing Profile` (legal name, address, GSTIN, `billing_mode` prepaid/postpaid, `min_balance`, spend alert) |
| **What you buy** | `Plan` + `Plan Rate` + `Plan Includes`; `Add-on` + `Add-on Rate` (metered overage) |
| **The agreement** | `Subscription` (per **team × cluster**, `account_standing` current/past_due/suspended, `billing_cycle`) |
| **What you owe** | `Invoice` + `Invoice Line Item` (tax: GST/VAT, TDS; `erpnext_sync`), `Price Lock` |
| **What you've metered** | `Usage Rollup` (per resource × meter × period, `meter_type` counter/gauge, `idempotency_key`) |
| **Prepaid balance** | `Credit Wallet` + `Credit Ledger Entry` |
| **Money movement** | `Payment Method`, `Payment Gateway`, `Payment Attempt`, `Refund`, `Mandate` |
| **Risk / caps** | `Trust Tier` + `Trust Tier Level`, `Entitlement Token` |
| **Plumbing** | `Webhook Event` (gateway callbacks), `Notification Log/Preference`, dunning |

> Note `Subscription` is scoped **per team _and_ cluster** — a team has a
> billing relationship *with each region* it uses. This fits the global/regional
> split: Central aggregates per-region subscriptions into one account view.

## Channel 1 — metering up (Atlas → Central)

Atlas's agent reports **rollups, never raw samples** (the app is explicit:
"Central stores only the Agent's rollups … ~one metered line per resource per
meter per month"), so Central's row count stays bounded.

```jsonc
// POST {central}/api/method/<press_billing ingest>   (HMAC, per-cluster — same as spec/07 W2′)
{
  "cluster": "bangalore",
  "resource_id": "bangalore-vm-9",         // == the registry asset name (spec/07 join key)
  "resource_type": "virtual_machine",
  "meter_type": "gauge",                    // gauge (e.g. RAM-hours) | counter (e.g. egress GB)
  "period_start": "2026-06-01T00:00:00Z",
  "period_end":   "2026-07-01T00:00:00Z",
  "quantity": 744, "unit": "vcpu_hour",
  "idempotency_key": "bangalore-vm-9:vcpu_hour:2026-06"
}
```

Central upserts a `Usage Rollup` (idempotent on `idempotency_key`) and prices it:

```
bill = max(0, quantity − locked_allowance) × locked_rate
```

where `locked_allowance` comes from the resource's `Price Lock` → `Plan.includes`
for that `resource_type`, and `locked_rate` from the matching metered `Add-on`'s
rate for the lock's currency + cluster (`press_billing/metering.py`). The result
becomes an `Invoice Line Item` at period close.

> The `resource_id` **is** the registry `name` from `spec/07`. The registry and
> the meter are joined by that key — Central can always answer "what did this
> asset cost" by walking registry → price lock → rollups.

## Channel 2 — entitlement down (Central → Atlas)

Central computes a **Trust Tier** from billing history (paid-invoice count +
cumulative paid; `press_billing/entitlements.py`) and the live account standing,
then **signs an `Entitlement Token`** and pushes it to the cluster. Its fields
(verbatim from the app) are exactly the regional enforcement levers:

```jsonc
{
  "team": "TEAM-00042",
  "suspend":   false,     // non-payment → true: stop running resources
  "terminate": true,      // false → region must refuse terminate (and Central-only teardown)
  "cluster_slices":  { "bangalore": { "max_resource_count": 25, "max_spend": 5000 } },
  "allowed_plans":          ["standard","performance"],
  "allowed_resource_types": ["virtual_machine"],
  "issued_at": "...", "expires_at": "...",
  "signature": "<over the canonical body, per-cluster key>"
}
```

Atlas verifies the signature offline (key from W1) and enforces at the decision
points that matter:
- **Provisioning gate:** refuse `vm:create` if it would exceed
  `cluster_slices.max_resource_count` or projected run-rate > `max_spend`, or if
  the plan/resource-type isn't allowed. (Note the app's distinction: promotion
  uses *historical paid*; the cluster's live check uses *projected run-rate* —
  two measures, never conflated.)
- **Standing gate:** `suspend=true` → stop/forbid start; `terminate=false` → the
  region refuses user-initiated terminate.

This is the **billing half of the AND gate** in `spec/06`: an action needs IAM
capability **and** entitlement. `vm:terminate` requires the member to hold the
capability *and* the token's `terminate=true`. Demotion (a lower tier) lowers the
cap only — it never stops running resources; stopping is a separate `suspend`
directive (so a price drop can't accidentally kill a fleet).

## Payments — the gateway adapter

`press_billing/gateways/` is an adapter pattern (`base.py` + `stripe_adapter`,
`razorpay_adapter`, `paypal_adapter`, `registry.py`). Central:
- selects a gateway per `Subscription`/`Payment Method`;
- drives charges through the adapter (`charges.py`, `payments.py`);
- receives gateway callbacks at a webhook endpoint, logging each to
  `Webhook Event` (idempotent, signature-verified — same discipline as `spec/07`
  ingest);
- runs **dunning** (`dunning.py`) on failure → retries → `past_due` →
  (eventually) a `suspend` entitlement directive.

**Modes** (`Billing Profile.billing_mode`):
- **Prepaid:** `Credit Wallet` balance; provisioning blocked below `min_balance`;
  usage debits the wallet via `Credit Ledger Entry`.
- **Postpaid:** periodic `Invoice` with `due_date`; non-payment → dunning → suspend.

## End-to-end lifecycle (where each plane acts)

```
create VM (Atlas)
  → Central: Price Lock (team, cluster, currency, plan, rate)         [lock the terms]
running…
  → Atlas agent: Usage Rollup pushed up monthly        (Channel 1)    [meter]
period close (Central)
  → price rollups vs locked allowance → Invoice + Line Items          [bill]
  → charge via gateway adapter (Stripe/…)                             [collect]
  → on success: Trust Tier recompute → new Entitlement Token down     (Channel 2)
  → on failure: dunning → past_due → suspend token down               (Channel 2)
```

Central owns every step except *meter* (Atlas) — and even that Central only
*receives*. No plane reaches past its neighbor.

## Integration contracts (what the other specs must honor)

- **IAM (`spec/06`):** add capabilities `billing:view`, `billing:manage` and gate
  the (Central-only) billing UI/methods on them — these ride in the OAuth token
  claim like every other capability. Billing *standing* (suspend/terminate) is a
  separate team-level concern delivered down to Atlas when billing is built (see
  the post-grilling note above), not via the per-user token.
- **Registry (`spec/07`):** `resource_id == registry name` — the join that lets
  Central walk registry → price lock → usage. Usage ingestion reuses the same
  service-account transport as the registry pull; if/when registry event-push is
  added (a deferred `spec/07` optimization), usage events become its sibling.
- **Frontend (`spec/09`):** billing is a **Central-only** surface (invoices,
  plans, payment methods, usage) under `/dashboard/billing`. Atlas never renders
  billing; it only *reacts* to entitlement (e.g. a disabled "Create VM" with a
  "billing on hold" reason surfaced from the token).

## Build order

1. **POC:** nothing — leave the seams (surrogate Team key; `resource_id` =
   registry name; per-cluster signing key at W1). 
2. **Billing v1:** install `press_billing` in Central; Plans + Subscriptions +
   prepaid Credit Wallet + Stripe; manual usage entry.
3. **Billing v2:** wire Channel 1 (Atlas agent → Usage Rollup) onto the `spec/07`
   ingest transport; automated invoicing + dunning.
4. **Billing v3:** wire Channel 2 (Entitlement Token) into Atlas's provisioning
   and standing gates, unified with the IAM signed-mirror verifier.
