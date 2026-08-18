# Billing demo dataset

A comprehensive, self-consistent billing dataset for demoing the console, the Desk
Catalog Administration workspace, and the eleven billing reports. Everything is authored
through the **real** code paths (Plan Configurator, provisioning, invoicing, settlement,
dunning, refunds, notifications) so the demo exercises production logic rather than
hand-injected rows.

```bash
# build (wipes ALL billing data first, then rebuilds the ten teams)
bench --site demo-billing.local execute central.billing.demo.demo_scenarios.seed

# post-seed roll-up (per-team scenario summary + aggregate counts)
bench --site demo-billing.local execute central.billing.demo.demo_scenarios.summary
```

- `demo_scenarios.py` — orchestration: the ten teams, their terminal states, the seed/summary entrypoints.
- `_factory.py` — the catalog shape (clusters, plans, tiers, gateways) and the idempotent record builders.

The current (open) billing month is **June 2026** (`ANCHOR = 2026-06-01`); "today" is 2026-07-05.

---

## Logins

| Who | Email | Password | Where |
| --- | --- | --- | --- |
| Operator (billing admin) | `billing_admin@example.com` | `Billing@2026` | Desk — Catalog Administration workspace, Plan Configurator, reports |
| Team owners | `owner-<slug>@example.com` | `abc@123` | Console (`/dashboard`) |

Each team also carries a roster (created disabled so they don't bootstrap their own teams):
`admin`, `dev`, `billing`, `viewer` (Active), `contractor` (Suspended), `invitee` (Invited),
plus one team-scoped custom role **Finance & Ops** (`billing:view/manage`, `server:view/power`) —
so the Members & Roles screen shows the full spread.

---

## Catalog

Authored through real **Plan Configurator** documents (`_vm_plans`, `_component_rate_card`,
`_service_catalog`) against the canonical taxonomy masters (`ensure_catalog_masters`).

**Regions** (a region bills in one currency; a team bills in ONE currency regardless of where it runs):

| Cluster | Label | Currency | Cost multiplier |
| --- | --- | --- | --- |
| `in-mumbai` | India — Mumbai | INR | 1.00× |
| `me-dubai` | Middle East — Dubai | USD | 1.15× |

**VM bundle ladder** (flat-rate plans; base price is monthly INR):

| Key | Title | vCPU / RAM / Disk | Transfer incl. | Base INR/mo |
| --- | --- | --- | --- | --- |
| `plan-1vcpu` | Starter | 1 / 2 GB / 25 GB | 100 GB | 1,500 |
| `plan-2vcpu` | Basic | 2 / 4 GB / 50 GB | 200 GB | 3,000 |
| `plan-4vcpu` | Standard | 4 / 8 GB / 100 GB | 400 GB | 6,000 |
| `plan-8vcpu` | Pro | 8 / 16 GB / 200 GB | 800 GB | 12,000 |
| `plan-16vcpu` | Enterprise | 16 / 32 GB / 400 GB | 1,600 GB | 24,000 |

**À-la-carte component rate card** (ADR 0009 — powers the "design your own" selector; INR base per unit/mo):
Compute **1,200**/vCPU · Memory **400**/GB · Disk **30**/GB. A composed config prices as
Σ(qty × component rate) and is only sellable when every component it uses is priced.

**Team-level metered consumer services** (ADR 0013/0015 — postpaid overage, per-unit priced,
allowance **0** = pure pay-per-use, so every reported unit bills):

| Slug | Family | Unit | INR / unit | USD / unit |
| --- | --- | --- | --- | --- |
| `svc-ai-tokens` | AI Tokens | Nos | 0.012 | 0.00015 |
| `svc-emails` | Emails | Nos | 0.007 | 0.00009 |
| `svc-pdf` | PDF Generation | Nos | 0.018 | 0.00022 |

**Gateways**: Stripe (INR), Stripe (USD, default card rail), Razorpay (INR, supports e-mandates),
PayPal (USD, non-default opt-in rail — ADR 0007). Demo keys are placeholders; credential
validation and webhook registration are skipped so the seed runs offline.

**Tax** (place of supply = billing currency): INR → GST 18%, USD → VAT 5%.

**Trust tiers** (`t0`–`t3`; the INR table, per-currency thresholds derived via FX USD=83):

| Tier | Spend cap (INR) | Max resources | Min paid invoices | Paid history in demo |
| --- | --- | --- | --- | --- |
| `t0` (default) | 5,000 | 3 | 0 | 0 months |
| `t1` | 50,000 | 25 | 1 | 2 months |
| `t2` | 200,000 | 100 | 6 | 5 months |
| `t3` | 1,000,000 | 500 | 10 | 9 months |

The tier ladder is mirrored across currencies: a USD team and an INR team at the same tier
carry the **same** number of paid historical invoices — the visible proof that a team is
promoted by settling invoices.

---

## The ten teams

Five billing in USD, five in INR, one per rung of the tier ladder. Each exercises a distinct
terminal (current-month) settlement/refund/dunning path, plus its historical months.

| Slug | Tier | Cur. | Scenario | Resources | Resize | Collection mode | Metered services |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `northwind` | t3 | USD | `bank_pending` | 12-instance fleet (2 regions) | — | Auto Charge | AI 260k, PDF 45k |
| `initech` | t2 | USD | `partial_card` | 4vCPU + 2vCPU (+ composed) | — | Auto Charge | Email 130k |
| `soylent` | t1 | USD | `dispute` | 2vCPU | — | Auto Charge | — |
| `globex` | t1 | USD | `fallback` | 2vCPU | — | Auto Charge | — |
| `harbor` | t0 | USD | `credits_full` | 1vCPU | same day | Prepaid | — |
| `acme-corp` | t3 | INR | `grandfathered` | 8+2+1 vCPU (Mumbai) | within 24h | Auto Charge | AI 280k, Email 90k |
| `umbrella` | t2 | INR | `overdue` | 4vCPU + 2vCPU (+ composed) | — | Manual Checkout | PDF 75k |
| `stark-ind` | t1 | INR | `retry` | 2vCPU | — | Manual Checkout | Email 90k |
| `hooli` | t1 | INR | `refund_wallet` | 1vCPU | — | Manual Checkout | — |
| `piedpiper` | t0 | INR | `credits_full` | 1vCPU | same day | Prepaid | — |

`initech` and `umbrella` also compose a **custom à-la-carte VM** (no preset Plan, priced from
the component rate card).

---

## Current-month scenarios

Each team's June invoice lands in one terminal state (`_finish_current_month`):

| State | Team(s) | What the current invoice shows |
| --- | --- | --- |
| `bank_pending` | northwind | A charge stuck in-flight — submitted to Stripe, still awaiting the bank (attempt `Initiated`, no webhook). The invoice is **frozen**: no Pay Now, no retry, until reconciliation resolves it. |
| `partial_card` | initech | Credits-then-card waterfall: the wallet (welcome credit) is drawn first, the remainder captured on the card. |
| `dispute` | soylent | Paid, then charged back — a full **chargeback → source**. The captured attempt flips to `Refunded`; the invoice **stays Paid** (GST immutability). |
| `fallback` | globex | **Autopay fallback (#28):** the primary card declines, settlement rotates to a backup card that captures. Then a **double charge by mistake** (the same invoice captured twice) is refunded **in full → source**. |
| `credits_full` | harbor, piedpiper | Settled fully from welcome credits — no card touched. |
| `grandfathered` | acme-corp | A locked launch (discounted, 0.78×) rate + metered overage; current invoice left Open. |
| `overdue` | umbrella | The prior (closed) month was dunned to **Overdue + suspended**; the current month is a fresh, not-yet-due Open invoice. |
| `retry` | stark-ind | One declined attempt (`card_declined`) then a successful capture. |
| `refund_wallet` | hooli | Paid, then a partial overcharge refunded **→ wallet** as credits. |

### Refund rule (as modelled)

Matches `billing/payments/refunds.py`:

- **Card / source refunds are the full-amount case** — a dispute chargeback (`soylent`) or a
  double charge refunded in full (`globex`). A full source refund flips the attempt to `Refunded`.
- **Partial overcharges always go to the wallet** as credit (`hooli`), applied on the next invoice.

### Settlement sources (ADR 0022 collection modes)

- **Auto Charge** — the saved method is debited off-session: a card for the four USD teams, a
  UPI Autopay mandate for `acme-corp`, which is held to the ₹15k silent ceiling and trips
  **Action Required** above it (its open invoice is over the ceiling, so the banner reads that).
- **Manual Checkout** — customer pays via a checkout link.
- **Prepaid** — settles from the wallet; no card on file.

---

## Historical months

Each tier carries N closed months of consolidated invoices before June (t1 = 2, t2 = 5, t3 = 9),
all settled to Paid. Coverage seeded across the history:

- **Credits-then-card waterfall** — non-credit-kept teams draw their welcome credit on their
  first bill, then the card settles the remainder.
- **Dunning-then-settle trails** (`_RETRY_HISTORY`) — some months show 1–2 declined card
  attempts before the capture, so the invoice Activity and the failed-payments report fill.
- **VM resizes** on the current bill: `same_day` (an upsize + downsize in one day — `harbor`,
  `piedpiper`) and `within_24h` (a second resize spanning midnight — `acme-corp`). Each resize is
  a day-weighted `Plan Changed` segment on the ledger (ADR 0010).
- **Metered overage** — reported service usage past the (zero) allowance bills on the period's invoice.

### Welcome credits are backdated to signup

Welcome credits ($25 / ₹2,500) are granted at signup, then drawn down by (backdated) invoices.
The grant's timestamp is backdated to before the team's first period (`backdate_welcome_credit`)
so the wallet timeline reads **grant → apply** and `get_balance` reads the balance off the actual
draw — not the stale seed-time grant. Without this a team that had spent its welcome credit still
showed the full amount.

---

## Notification feed

`_seed_notification_feed` exercises the real writers so the console bell/inbox is demoable across
both categories:

- **Billing** (via `notifications.notify`): Payment Success/Failure, Card Expiry, Credit Low,
  Mandate Reauth, Pre-debit Notice — one representative event per team, matched to its scenario.
- **Server**: Server Failed (a real `Asset` flipped to `Failed` fires the `on_update` hook),
  Resize Failed and Cluster Degraded (via `create_notification`, the same writer the real hooks call).
- The `overdue` team already emits Invoice Overdue + Server Suspended through real dunning.

---

## Conventions

- **Money stays in one currency per team.** Reports split money into per-currency columns; INR and
  USD are never mixed or summed in one column/tile/total.
- **Authored via code paths, never hand-injected.** Plans go through the configurator, invoices
  through `generate_team_invoice`/`open_and_collect`, dunning through `process_invoice_dunning`,
  refunds through the Refund doctype — so the demo would surface a real bug rather than mask it.
  The only stand-ins are for the offline gateways (payment captures are simulated), and backdating
  helpers that pin seed-time records to their in-story moment.
- **Idempotent.** A re-seed wipes all billing data and reuses the same owner Teams (`_wipe_all`,
  `_ensure_demo_team`), so counts stay stable across runs.
