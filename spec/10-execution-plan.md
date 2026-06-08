# 10 — Execution Plan (IAM: auth + permissions, Central ↔ Atlas)

The path to shipping the **IAM layer** — identity/teams/roles/permissions in
Central, enforced in Atlas (`spec/06`) over the OAuth SSO (`spec/03`). Ordering is
**tracer-bullet**: every phase is a thin vertical slice that works end-to-end and
de-risks the next. Nothing is big-bang; each phase ships on its own.

The load-bearing simplification: **permissions ride in the OAuth token Central
already issues, not a bespoke signed mirror** — so there is no new permission
channel to build (`spec/06`).

## Phase 0 — POC (validated, then discarded)

> **The POC's *code* is being thrown away, not extended.** It proved the approach
> end-to-end (SSO works, the registry/W4 model works) — that learning stands —
> but the build restarts from a **fresh Central app** at Phase 1. Treat the
> POC code below as a reference that validated the design, not a foundation to
> build on.

Already built and verified end-to-end on a two-site bench (`frappe.local` =
Central, `development.localhost` = Atlas):

- Central app: `Team` (surrogate key + editable `team_name`), `Team Member`,
  `Cluster`, `Virtual Machine` registry; `permissions.py` (team row-scoping via
  `permission_query_conditions`); `sync.py` (full pull + idempotent upsert);
  `api.py` (`get_vm_status` W4 cached, `sync_cluster`); `www/dashboard.py` gate;
  frappe-ui SPA (registry list + lazy status).
- **OAuth2 SSO** working: Central is the provider, Atlas a Social Login client;
  a Central user lands in Atlas signed-in, verified by driving the full flow.
- Ownership today is the **interim** `owner-email → personal team` mapping — the
  thing the team-attribution work (Phase 3) replaces.

## Phase 1 — the bare IAM data model on a **fresh** Central app (no code)

**Status:** implemented in `fc-v2-bench/apps/central` for `central.site`.

**Goal:** a clean slate. Build a **new Central app** carrying over none of the
current machinery (no `seed_iam`, `sync.py`, `oauth_claims.py`, `bootstrap.py`) —
just the IAM DocTypes and their predefined records. **Records ship as fixtures**,
the declarative Frappe way — *not* an imperative seed function.

| Change | Where |
|---|---|
| The five DocTypes: `Team`, `Team Member` (child), `Team Role`, `Role Capability` (child), `Capability`; `Team Member.role` = required `Link → Team Role`; `track_changes` on `Team`/`Team Role` | Central |
| **Fixtures**: the `Capability` catalog (central + atlas planes, no bench) + the system `Team Role`s `Owner/Admin/Developer/Viewer/Billing` (`is_system=1`) with their capability bundles | Central |
| Signup bootstrap: new enabled non-system Users get native `Central User`, a default Team, and an active Owner `Team Member` row | Central |

**Ships:** the data model exists and an admin can assign real roles to members.
**Done bar:** a clean `bench migrate` on a fresh site re-creates every record
from fixtures alone — no enforcement, no claim, nothing else yet. (Records,
catalog, and role→capability mapping are specified in `spec/06` and
`spec/prompts/iam-implementation-prompt.md`.)

## Phase 2 — `fc_teams` token claim (the spine)

**Status:** Central-side resolver and OAuth claim injection are implemented.
Atlas session capture is still deferred.

**Goal:** carry permissions to Atlas in the token. Still observe-only.

| Change | Where |
|---|---|
| Inject `fc_teams` ( `{team → role + caps}` ) into the OIDC token / `openid_profile`; currently done through an isolated `central.oauth` patch because this Frappe version has no custom-claim hook | Central |
| Read `fc_teams` from the token into the Atlas session on SSO login | **Atlas** |

**Ships:** Atlas *has* the user's capabilities in-session and can log/inspect
them — but doesn't gate on them yet. This isolates the riskiest integration (the
custom claim end-to-end) in one small, observable step.

## Phase 3 — team attribution, team-in-path & enforcement (the payoff)

**Goal:** real RBAC + correct team ownership, end to end. This is the big
cross-plane phase.

| Change | Where |
|---|---|
| Add nullable `team` field to `Virtual Machine` (opaque `Team.name`) | **Atlas** |
| Routes → `/dashboard/t/<team>/machines/:name`; `www` gate echoes the full path (deep-link fix) | **Atlas** |
| Stamp `VM.team = <path team>` on create, gated by `can("vm:create", team)` | **Atlas** |
| Gate `start/stop/terminate/resize` whitelisted methods on `fc_teams[pathTeam].caps` | **Atlas** |
| List scoping at `/t/<team>/machines` → that team's VMs | **Atlas** |
| Build team-scoped deep links; team picker on "create" / "open console" | Central |

**Ships:** "Dana (Admin) can terminate, Sam (Operator) can't"; VMs are owned by
the *right* team (not a personal team); opening a VM lands on the exact machine.
The multi-tenant IAM story is now correct, end to end.

## Phase 4 — hardening & polish

- **Bound revocation freshness** to a short clock (short Atlas session forcing
  warm re-SSO, or a scheduled `fc_teams` refresh) — so a revoked role takes
  effect promptly, not at the end of a multi-day session.
- **Scope the registry/service account** read-only (don't leave it `System Manager`).
- **Custom per-team roles** (the rare ~10%, already allowed by the model).
- Tighten the account-disable bound only if the token-lifetime window proves too
  loose (then revisit the `OPEN-QUESTION`).

## Deferred by design (each with a trigger)

Built only when its trigger fires — not before:

| Deferred item | Trigger |
|---|---|
| Finer-than-team scoping via **Resource Groups** (designed; additive IAM v2, `spec/06`) | a real need to differ permissions within a team's VMs |
| **Bench permission layer** (`spec/06`) | Bench gets user-facing actions |

> Non-IAM concerns (asset registry sync, the seamless frontend/shared package,
> billing) are **out of scope for this ship** and their specs are archived under
> `spec/archive/`.

## Atlas-side change inventory (cross-repo dependencies)

Atlas is upstream (`adityahase/atlas`); these are the coordinated changes it
needs, all small and additive (tracked in `OPEN-QUESTIONS`):

1. **Read the `fc_teams` claim** into the session on SSO login. *(remaining Phase 2)*
2. **`Virtual Machine.team`** field + stamp it on create. *(Phase 3)*
3. **Team-in-path routing** + **deep-link `redirect-to` fix** in `www/dashboard.py`. *(Phase 3)*
4. **Capability gates** on the VM lifecycle whitelisted methods. *(Phase 3)*

Everything else lives in Central or the new shared frontend package — so Atlas's
footprint stays minimal and its standalone operability (plain session auth) is
untouched.

## Sequencing rationale

Phases 1→2→3 deliver permissions as one widening slice (**model → transport →
enforcement**), so the custom-claim and team-in-path risks are each isolated and
observable before anything *enforces*. Phase 1 alone (the bare data model from
fixtures) is shippable and reversible; Phase 2 makes Atlas *aware* without gating;
only Phase 3 turns enforcement on. Hardening (Phase 4) follows once the path
works. Resource Groups and a Bench layer are deliberately deferred behind real
triggers — most likely to be over-built if pulled forward.
