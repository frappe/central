# Team-level metered services — API reference

> Bill a service by its usage — AI tokens, email, PDF rendering, storage — attributed to a
> **team**, with no server involved. A consumer service subscribes, reports usage, and Central
> meters it onto the same invoice as everything else. Design decisions live in the `billing-specs`
> repo: **ADR 0015** (this API contract) and **ADR 0013** (the synthesized subject).

**Source of truth**

| Concern | File |
| --- | --- |
| Pilot (consumer-service) facade | `central/billing/api/billing_api.py` |
| Customer dashboard endpoints | `central/billing/api/dashboard/services.py` |
| Admin console endpoints | `central/billing/api/admin/services.py` |
| Read models (plans / subscriptions / allowance / subject resolution) | `central/billing/catalog/services.py` |
| Provisioning (synthesized subject) | `central/billing/catalog/subscriptions.py` → `provision_service_subscription` |
| Usage ingestion (dual-mode) | `central/billing/revenue/metering.py` → `ingest_rollup` |
| Tests | `central/billing/tests/test_service_metering.py` |

---

## Overview

A **team-level metered service** has no customer VM. When a team subscribes, Central mints a
synthesized *subject* keyed on `(team, service family, cluster)` and opens a price-lock segment —
the caller never handles that subject. Usage lands as one bounded rollup row per period and bills
off the same spine as any server.

- **You name the service.** A consumer service calls `report_usage(service, quantity)`. Central
  derives the team (from the credential), the subject, the billing period, and the idempotency key.
- **Two service shapes.** A *bundle* (e.g. `$20 → 1M tokens`) carries an included allowance; a
  *pure meter* (e.g. `$0.0001/PDF`) is per-unit with no allowance.
- **Cluster is optional.** Most services are globally priced — subscribe once, report from
  anywhere. `cluster` only matters for the minority that price per region.

---

## Authentication

Three surfaces, three audiences. The team is never widened by a parameter beyond what the caller is
allowed to touch.

| Surface | Path root | Auth | Team |
| --- | --- | --- | --- |
| Consumer service (pilot) | `central.billing.api.billing_api.*` | Header `X-Pilot-Token` | From the credential — a caller only ever touches its own team. |
| Customer dashboard | `central.billing.api.dashboard.*` | Session cookie `sid` | Caller's team; capability `billing:view` / `billing:manage`. |
| Admin console | `central.billing.api.admin.services.*` | Session cookie `sid` | Any team (explicit param); operator / System Manager only. |

---

## Conventions

- **URL** — `https://<site>/api/v2/method/<dotted.path>`
- **Params** — `GET` → query string; `POST` → JSON body with `Content-Type: application/json`.
- **Success** — HTTP 200, body `{ "message": <payload> }`. Payloads below are the *inner* value.

---

## Reporting & settlement modes

Both are properties of the service **family** (the plan's `Plan Category`) — a consumer service
doesn't choose them per call, it just honors them.

### Reporting mode — how usage is sent

| Mode | Caller sends | Central does | Typical |
| --- | --- | --- | --- |
| `Authoritative` | The period's running total, each report. | Replaces the period quantity. | Token manager, email — services keeping their own ledger. |
| `Incremental` | A delta, plus a `sequence` that bumps each flush. | Accumulates; a duplicate / stale / out-of-order sequence is a no-op. | Micro-services (PDF) aggregating at the edge. |

> **Dedup.** Central can invent the subject, period and key — but not the dedup token. Only the
> caller knows a retry from a new increment, so incremental exactly-once needs one bumping integer
> (`sequence`). Omit it for best-effort (a rare retry may double-count).

### Settlement mode — what a used-up allowance means

| Mode | Behavior | Billing |
| --- | --- | --- |
| `Postpaid Overage` | Keep serving past the allowance. | Bills `max(0, qty − allowance) × rate` at period close. |
| `Prepaid Pack` | Allowance is a purchased balance; `blocked` flips true at zero. | Bills nothing — the pack was paid up front; excess is blocked, not charged. |

---

## Consumer service · pilot

All pilot endpoints require the `X-Pilot-Token` header and take the team from the credential.

### `GET` list_service_plans

Active service plans, priced for the team's currency.

| Name | In | Type | Req | Description |
| --- | --- | --- | --- | --- |
| `cluster` | query | string | optional | Region for a regionally-priced family; omit for global. |

```bash
curl -s '.../central.billing.api.billing_api.list_service_plans' \
  -H 'X-Pilot-Token: <token>'
```
```jsonc
{ "message": {
  "currency": "INR",
  "plans": [{
    "plan": "meter-tokens", "title": "AI Tokens", "billing_type": "Metered",
    "settlement_mode": "Postpaid Overage", "reporting_mode": "Authoritative",
    "resource_type": "Tokens", "unit": "1M tokens", "allowance": 0.0, "rate": 5.0, "currency": "INR"
  }]
} }
```

### `POST` subscribe_service

Subscribe the team to a service — mints the synthesized subject and opens the price-lock segment.
Idempotent per `(team, family, cluster)`; a different plan in the same family is an in-place
`upgraded` re-lock.

| Name | In | Type | Req | Description |
| --- | --- | --- | --- | --- |
| `plan` | body | string | **required** | Plan name from `list_service_plans`. |
| `cluster` | body | string | optional | Region; omit for a global subscription. |

```bash
curl -s -X POST '.../central.billing.api.billing_api.subscribe_service' \
  -H 'X-Pilot-Token: <token>' -H 'Content-Type: application/json' \
  -d '{"plan":"meter-tokens"}'
```
```jsonc
{ "message": {
  "subscription": "a1b2c3", "service_subject": "svc-9f3a1c7e2b4d6a80",
  "reused": false, "upgraded": false, "locked_rate": 5.0, "currency": "INR"
} }
```

### `GET` get_service_subscription

The team's active service subscriptions, each with plan, modes, allowance, and usage reported this
period. No parameters.

```bash
curl -s '.../central.billing.api.billing_api.get_service_subscription' \
  -H 'X-Pilot-Token: <token>'
```
```jsonc
{ "message": {
  "services": [{
    "subscription": "a1b2c3", "service_subject": "svc-9f3a…", "plan": "meter-tokens",
    "title": "AI Tokens", "cluster": null, "currency": "INR", "locked_rate": 5.0,
    "billing_type": "Metered", "settlement_mode": "Postpaid Overage", "reporting_mode": "Authoritative",
    "resource_type": "Tokens", "unit": "1M tokens", "allowance": 0.0, "period_usage": 500.0
  }]
} }
```

### `GET` check_service_allowance

Allowance state for edge enforcement, by the service the caller *is*. A prepaid service polls this
and degrades when `blocked`; a postpaid service never blocks.

| Name | In | Type | Req | Description |
| --- | --- | --- | --- | --- |
| `service` | query | string | **required** | The metered Resource Type the family covers (e.g. `Tokens`). |
| `cluster` | query | string | optional | Region hint; the global subject is the fallback. |

```bash
curl -s '.../central.billing.api.billing_api.check_service_allowance?service=Tokens' \
  -H 'X-Pilot-Token: <token>'
```
```jsonc
{ "message": {
  "exists": true, "service_subject": "svc-9f3a…", "plan": "meter-tokens",
  "settlement_mode": "Prepaid Pack", "unit": "1M tokens",
  "allowance": 1000.0, "used": 1000.0, "remaining": 0.0, "blocked": true
} }
// not subscribed → { "message": { "exists": false } }
```

### `POST` report_usage

The core call. Name the `service` you are and the `quantity`; Central derives team, subject, period,
and idempotency key.

| Name | In | Type | Req | Description |
| --- | --- | --- | --- | --- |
| `service` | body | string | **required** | The metered Resource Type (e.g. `PDF Render`). |
| `quantity` | body | number | **required** | Authoritative: the period running total. Incremental: the delta since last report. |
| `cluster` | body | string | optional | Regional services only; omit for global. |
| `sequence` | body | int | optional | Incremental exactly-once: a monotonic counter, bumped each flush. Default `0`. |
| `period` | body | string | optional | `"YYYY-MM"` to backfill a past month; defaults to the current one. |

```bash
# incremental micro-service
curl -s -X POST '.../central.billing.api.billing_api.report_usage' \
  -H 'X-Pilot-Token: <token>' -H 'Content-Type: application/json' \
  -d '{"service":"PDF Render","quantity":500,"sequence":7}'

# fire-and-forget: {"service":"PDF Render","quantity":1}
# authoritative:  {"service":"Tokens","quantity":500}
```
```jsonc
{ "message": { "recorded": true, "service_subject": "svc-9f3a1c7e2b4d6a80" } }
// recorded=false → no open billing segment yet for the subject (not an error)
```

---

## Customer dashboard

Session-authed; team defaults to the caller's own.

### `GET` get_metered_services  — `billing:view`

The team's metered footprint plus the catalog it can subscribe to, priced for its currency. Backs
the console's Metered services card.

| Name | In | Type | Req | Description |
| --- | --- | --- | --- | --- |
| `team` | query | string | optional | Defaults to the caller's team. |
| `cluster` | query | string | optional | Prices the catalog for a region. |

```bash
curl -s '.../central.billing.api.dashboard.get_metered_services' -b 'sid=<session>'
```
```jsonc
{ "message": {
  "currency": "INR",
  "services": [ /* as get_service_subscription */ ],
  "available_plans": [ /* as list_service_plans */ ]
} }
```

### `POST` subscribe_metered_service  — `billing:manage`

Subscribe the team, or upgrade it onto a different plan in the same family. Same result shape as
`subscribe_service`.

| Name | In | Type | Req | Description |
| --- | --- | --- | --- | --- |
| `plan` | body | string | **required** | Plan to subscribe / upgrade to. |
| `cluster` | body | string | optional | Region; omit for global. |
| `team` | body | string | optional | Defaults to the caller's team. |

```bash
curl -s -X POST '.../central.billing.api.dashboard.subscribe_metered_service' \
  -b 'sid=<session>' -H 'Content-Type: application/json' \
  -d '{"plan":"meter-tokens"}'
```

---

## Admin console

Operator / System Manager only; the team is an explicit parameter.

### `GET` get_team_services

Any team's metered footprint plus the catalog it can subscribe to.

| Name | In | Type | Req | Description |
| --- | --- | --- | --- | --- |
| `team` | query | string | **required** | The team to inspect. |
| `cluster` | query | string | optional | Prices the catalog for a region. |

```bash
curl -s '.../central.billing.api.admin.services.get_team_services?team=acme' -b 'sid=<operator>'
```
```jsonc
{ "message": { "team": "acme", "currency": "INR", "services": [ … ], "available_plans": [ … ] } }
```

### `POST` subscribe_team_service

Subscribe a team to a service, or upgrade its plan — from the admin console. Same result shape as
`subscribe_service`.

| Name | In | Type | Req | Description |
| --- | --- | --- | --- | --- |
| `team` | body | string | **required** | The team to subscribe. |
| `plan` | body | string | **required** | Plan to subscribe / upgrade to. |
| `cluster` | body | string | optional | Region; omit for global. |

```bash
curl -s -X POST '.../central.billing.api.admin.services.subscribe_team_service' \
  -b 'sid=<operator>' -H 'Content-Type: application/json' \
  -d '{"team":"acme","plan":"meter-tokens"}'
```

---

## Errors

Failures return a non-200 with a Frappe exception payload. The common ones:

| HTTP | Exception | When |
| --- | --- | --- |
| 401 | `AuthenticationError` | Missing / invalid / expired `X-Pilot-Token`. |
| 403 | `PermissionError` | Session lacks `billing:manage`, or a non-operator hits an admin path. |
| 417 | `ValidationError` | Team not subscribed to the service; billing profile incomplete; a server plan subscribed as a service. |

> `report_usage` returning `{ "recorded": false }` is **not** an error — it means the subject has no
> open billing segment yet (nothing to bill against), distinct from a 417 for an unsubscribed service.

---

## Quick test flow

Prove the whole path end to end: discover → subscribe → report → verify it bills.

1. `list_service_plans` → pick a `plan` and its `resource_type`.
2. `subscribe_service(plan)` → note `service_subject`.
3. `report_usage(service, quantity)` → expect `recorded: true`.
4. `check_service_allowance(service)` → confirm `used` moved.
5. Run invoicing for the month → a metered line `(qty − allowance) × rate` appears (postpaid), or
   none (prepaid).

**Incremental dedup check** — retries and stale batches must be no-ops:

```
report_usage(service="PDF Render", quantity=100, sequence=1)  → 100
report_usage(service="PDF Render", quantity=50,  sequence=2)  → 150
report_usage(service="PDF Render", quantity=50,  sequence=2)  → 150  (duplicate, no-op)
report_usage(service="PDF Render", quantity=999, sequence=1)  → 150  (stale, no-op)
```

**Server-side (no auth)** — drive the same code via `bench --site <site> console`:

```python
import frappe, inspect
from central.billing.api import billing_api
frappe.local.pilot_credential = frappe._dict(team="your-team")   # stub the credential
call = lambda f, **k: inspect.unwrap(getattr(billing_api, f))(**k)

plan = call("list_service_plans")["plans"][0]
sub  = call("subscribe_service", plan=plan["plan"])
print(call("report_usage", service=plan["resource_type"], quantity=500))
print(call("check_service_allowance", service=plan["resource_type"]))
frappe.db.rollback()   # drop the test data
```
