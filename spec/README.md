# Central — Specification

This `spec/` directory is the **source of truth** for Central. Code serves the
spec, not the other way around. (Same convention as Atlas.)

## Purpose

Central is the **global control plane and front door** of Frappe Cloud. A user
signs into Central once and from there can see every asset they own across every
region and step into any of them without signing in again.

Central owns three things and nothing more (for v1):

1. **Identity & ownership** — Users, Teams, and who-owns-what.
2. **The asset registry** — a global, eventually-consistent index of what exists
   and which Team owns it. *Identity, not runtime state.*
3. **Routing** — single sign-on hand-off into the correct Atlas cluster.

## First principles (the load-bearing rules)

1. **Identity & ownership are global; runtime state is regional.**
   Central stores *that* `vm-42` exists and *who* owns it. It does **not** store
   whether `vm-42` is running — that is fetched live from Atlas on demand and
   cached briefly. Two sources of truth for the same fact is the bug we are
   designing against.

2. **Hand-off over integration.**
   To operate an asset, Central **redirects** the user into Atlas with an SSO
   token. Central does not proxy Atlas's UI or replicate its data.

3. **The global plane is never in a region's critical path, and vice-versa.**
   - Central down ⇒ users can't see the global list, but each Atlas cluster is
     still reachable and operable directly, and running sites keep serving.
   - A cluster down ⇒ Central still renders the registry; only that cluster's
     rows show "status unavailable". The dashboard never blocks on a slow region.

4. **Standard framework components first.**
   Use Frappe's built-in auth, OAuth2 provider, REST API, and frappe-ui
   components even when a hand-rolled version would be shorter. The maintenance
   bar is the standard library.

5. **Central authors authority; the region enforces it from the short-lived
   OAuth token — no second channel.** Permissions are defined, granted, and
   revoked *only* in Central (`spec/06`). They reach Atlas as a claim in the
   OAuth/OIDC token Central already issues; Atlas enforces from the session,
   never calling Central per action. A Central outage thus can't take a region
   down — existing sessions run to token expiry, only new logins fail — and that
   behaviour falls out of how OAuth already works, with nothing bespoke to build.
   Identity and authority flow **down** (in the token); usage and inventory flow
   **up** (the registry pull); neither plane sits in the other's synchronous path
   (the corollary of rule 3). *(This replaced an earlier design that built a
   bespoke signed policy-mirror with push/pull and offline verification — dropped
   as over-engineering once we realised the OAuth token already is that artifact;
   see `spec/10`.)*

## The spec set (this ship = the IAM layer)

This directory is pruned to what's needed to **ship IAM (auth + permissions) in
Central, integrated with Atlas**:

- [`01-architecture.md`](01-architecture.md) — the global/regional model + blast-radius principles IAM rests on.
- [`03-auth-and-sso.md`](03-auth-and-sso.md) — OAuth2 SSO, the `fc_teams` token claim, the deep-link fix (the **auth** half).
- [`06-iam.md`](06-iam.md) — teams, roles, capabilities, token-carried enforcement (the **permission** half — the core).
- [`10-execution-plan.md`](10-execution-plan.md) — the phased plan to build it.
- [`prompts/iam-implementation-prompt.md`](prompts/iam-implementation-prompt.md) — the actionable build brief for an agent.

> Non-IAM specs (asset registry sync, the seamless frontend/shared package,
> billing, the POC data-model & frontend docs) are **archived under
> [`archive/`](archive/)** — out of scope for this ship, kept for later.

## Scope

**In scope (v1):** login, OAuth2 SSO into Atlas, the Cluster registry of Atlas
instances, the Virtual Machine asset registry (synced from Atlas), and the
registry list view.

**Out of scope (v1):** billing, consumption, invoices, payments, wallets,
notifications, marketplace, app/site management UI, team-invite flows, custom
domains. The data model anticipates Teams and asset hierarchy so these can be
added without migration churn, but none are specified here.

**Not Central's job, ever:** provisioning servers or VMs, running `bench`,
holding SSH keys to the fleet, or storing live runtime metrics. Those belong to
Atlas and Bench.

## Glossary

- **Cluster** — one Atlas instance serving one region (e.g. `bangalore`), reached
  at a base URL like `https://bangalore.x.frappe.dev`.
- **Asset** — anything a Team can own and reach. v1 asset type: **Virtual
  Machine**. Future: Site, App.
- **Registry** — Central's global index of assets and their owners.
- **Hand-off / routing** — the SSO redirect that takes a signed-in Central user
  into an Atlas cluster with a live session, landing on a specific page.
