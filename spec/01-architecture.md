# 01 — Architecture

## The global / regional split

Frappe Cloud v2 follows the same shape every large cloud uses: a small **global
plane** for identity and account-level concerns, and **N independent regional
planes** that hold the real control plane for compute.

```
                         ┌──────────────────────────────────────┐
                         │            USER (browser)             │
                         └───────────────────┬───────────────────┘
                            login + registry │  ▲ select asset → SSO redirect
                                             ▼  │
        ┌────────────────────────────────────────────────────────────────┐
        │  CENTRAL   (global, one instance)        cloud.frappe.io          │
        │  • Identity & Teams (IAM)                                         │
        │  • Cluster directory (where every Atlas lives)                   │
        │  • Asset registry (what exists + who owns it — NO runtime state) │
        │  • OAuth2 provider (SSO) + routing                               │
        └───────┬───────────────────────────────────────────▲─────────────┘
        (W2)pull│ VM list      (W3) OAuth2 SSO   (W4) live   │ (W1) cluster
         + (W4) │ live status   redirect          status     │ registration
                ▼                                            │ + credentials
        ┌────────────────────────┐   ┌────────────────────────┐
        │ ATLAS  bangalore        │   │ ATLAS  singapore   ...  │  ← each an
        │ bangalore.x.frappe.dev  │   │ singapore.x.frappe.dev  │    independent
        │ Servers + Firecracker   │   │                         │    failure domain
        └───────────┬─────────────┘   └─────────────────────────┘
            ssh Tasks│
                     ▼
              VMs (future: bench inside)   ← invisible to Central
```

Central's horizon **stops at Atlas**. It never talks to Bench or to a VM. Bench
is an implementation detail inside a cluster.

## The four wires

Everything Central does to/with a cluster is one of four well-defined channels.

| # | Wire | Direction | Sync? | Mechanism | Fails how? |
|---|---|---|---|---|---|
| **W1** | Cluster registration + credentials | setup | — | An admin registers a Cluster row with its base URL, an Atlas **API key/secret** (for W2/W4) and an **OAuth2 client** (for W3) | n/a |
| **W2** | Registry sync | Central → Atlas | async (scheduled + on-demand) | Central calls Atlas's standard REST API (`frappe.client.get_list` on `Virtual Machine`) and upserts registry rows | stale rows; flagged `last_synced` |
| **W3** | SSO hand-off | Central → Atlas (user) | sync | OAuth2 authorization-code flow; Central is provider, Atlas is client | user sees Atlas login screen |
| **W4** | Live status read-through | Central → Atlas | sync, lazy | On demand per asset, Central calls Atlas REST for current status; cached 30–60s in Redis | row shows "status unavailable" |

**Why pull (W2) instead of push?** Atlas today has **no event-callback code** —
it exposes a standard Frappe REST API and nothing more. So v1 requires *zero
changes to Atlas* for the registry: Central pulls. When Atlas later grows event
callbacks, W2 flips to push (Atlas → Central `handle_event`) with no change to
the rest of Central. The registry contract (rows keyed by Atlas VM id + cluster)
is identical either way.

## Blast-radius rules (non-negotiable)

1. **The list view is rendered from Central's own registry rows (W2 cache), never
   by fanning out synchronous calls to clusters on page load.** A slow or dead
   region must not delay the dashboard.
2. **Live status (W4) is lazy and per-row** — fetched after the list renders, in
   parallel, each cancellable, each failing independently to "unavailable".
3. **Central degrades to read-only-registry if all clusters are unreachable.**
   You can still see what you own; you just can't see live state or hand off.
4. **A cluster never calls Central synchronously to serve its own pages.** Atlas
   works standalone (it already does — plain Frappe session auth).

## How Central relates to Atlas's reality (verified against the repo)

- Atlas's user-facing unit is **`Virtual Machine`** (DocType). There is **no
  Site/App/Bench** doctype yet. So Central's v1 registry asset = Virtual Machine.
- Atlas serves a Vue SPA at `/dashboard` with routes `/dashboard/machines` and
  `/dashboard/machines/:name`. **These are Central's routing targets** (W3).
- Atlas auth today is **plain Frappe session cookie + CSRF**, gated server-side in
  `www/dashboard.py` (Guest → `/login?redirect-to=...`). There is **no SSO
  endpoint yet** — so the OAuth2 client side on Atlas (a Social Login Key +
  callback) is **new work on Atlas** that this spec depends on. See `spec/03`.

## Tech stack

- **Frappe** (Python + MariaDB). Central is a Frappe app; all state is DocTypes.
- **SPA:** frappe-ui `^0.1.278`, Vue 3, vue-router 4, Tailwind 3.4, Vite 5 — same
  versions as Atlas. Served at `/dashboard`, gated by `www/dashboard.py`.
- **Auth/SSO:** Frappe native login + Social Login (Google/GitHub) for users;
  Frappe **OAuth2 provider** (`frappe.integrations.oauth2`) for cluster SSO.
- **API:** standard Frappe REST only.
- **Cache:** Redis for W4 live-status (TTL 30–60s).
