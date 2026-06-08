# Implementation Prompt — Central/Atlas IAM (RBAC over OAuth)

> Paste this to an implementation agent (it has repo access **and a browser**), or
> follow it yourself. **First produce the plan; get it approved; then build.**

---

## Your task

Implement the **team-scoped, role-based permission system** for Frappe Cloud v2
across **Central** (authority) and **Atlas** (enforcement), per the settled
design. The mechanism is decided — **do not redesign it.** Your job is a clean,
simple, auditable implementation plus the work to finish what's only partly built.

**Deliver in two steps:**
1. **A plan** — an ordered list of tiny, independently-shippable steps (each a
   single concern, each verifiable in the running app). Show it and stop for
   review.
2. **The implementation** — execute the approved plan, verifying each step in the
   browser against the two running sites before moving on.

## Read first (these are the source of truth — do not re-derive)

- `spec/06-iam.md` — the IAM model (Team/Role/Capability, token-carried caps).
- `spec/03-auth-and-sso.md` — OAuth2 SSO, the `fc_teams` claim, deep-link fix.
- `spec/10-execution-plan.md` — phasing; this task is **Phases 1–3** of it.
- Old POC code: `apps/central/central/` — **reference only, being discarded.** You
  may read its `doctype/*.json` to copy field shapes, but carry over **no** logic
  (`iam.py`/`oauth_claims.py`/`sync.py`/`bootstrap.py` are not reused).
- Memory: `memory/central-atlas-local-setup.md` — sites, demo users, how to run.

**Start fresh — do NOT reuse the current code.** The existing `central` app has
grown machinery we are deliberately dropping (`seed_iam()`, `sync.py`,
`oauth_claims.py`, `bootstrap.py`). Build a **new, clean Central app** and carry
over *nothing* but the design in the specs. The first deliverable is the **bare
data model only** (Phase 1 below) — DocTypes plus their predefined records shipped
as **fixtures** (the declarative Frappe way; **no imperative seed function**).
Enforcement, the `fc_teams` claim, team-in-path, and the partner path are *later*
phases — do not write that code as part of the bare build.

## Hard principles (lessons from press / FC v1 — treat as acceptance criteria)

1. **One clear information hierarchy** (define it explicitly in your plan):
   `Capability` (atomic action, the vocabulary) → `Team Role` (a bundle of
   capabilities) → `Team Member` (user ↔ role *within one team*) → a user's
   effective permissions. Nothing grants capabilities except this chain.
2. **Predefined roles do 80–90% of the work.** Ship a small set of **system
   roles** that cover almost everyone; **custom (team-scoped) roles are the rare
   ~10% escape hatch**, not the default. Make custom roles possible but clearly
   secondary in both data model and UI.
3. **Single source of truth, auditable.** A user's caps for a team come from
   **exactly one place** (the chain above). Every grant is a **document** with
   owner + timestamps + `track_changes`, so "who can do what, and who granted it"
   is answerable by listing records — never inferred from scattered code.
4. **Never grant access through multiple independent paths.** There is **one**
   resolver and **one** membership path per user-type. Specifically:
   - The team **owner is a `Team Member` with the `Owner` role** (already done) —
     *not* a separate "if user == owner" bypass.
   - The **only** documented exception is the operator `System Manager` short-
     circuit; it must be in exactly one place and commented as the sole bypass.
   - No per-user capability overrides (the design already dropped them — keep it
     that way).
5. **Reuse Frappe; no bespoke crypto, no second permission channel.** Permissions
   ride in the OAuth token Central already issues (`fc_teams`). Enforcement is a
   local session lookup in Atlas — never a per-action call to Central.

## The predefined role set to seed (refine caps in your plan)

| Role | Intent | (you map the exact capabilities) |
|---|---|---|
| **Owner** | full control incl. team membership + billing + delete | all |
| **Admin** | manage members + all VM actions; not billing/delete | `team:manage_members`, all `vm:*` |
| **Developer** | operate & create VMs; no team/billing management | `vm:create/start/stop/resize/terminate/view`, `asset:view` |
| **Viewer** | read-only | `*:view` |
| **Billing** | billing only + read assets | `billing:view/manage`, `asset:view` |

Keep `Capability` as the **append-only catalog** and the single source for "what
actions exist." Roles reference capabilities; never inline raw strings elsewhere.

## Partner permissions — decoupled (you asked for options; pick one in the plan)

Partners (resellers/agencies) get access to client teams but **must not be
entangled with normal members**. Keep their path **separate, explicit, and
independently revocable** so "remove all partner access" is one clean action and
the audit clearly distinguishes partner vs member access.

- **Option A (recommended): a separate `Partner Access` DocType** —
  `partner` (the partner team/user), `team` (the client team), `role`
  (Link → Team Role, e.g. a `Partner Admin` system role), `granted_by`,
  `expires_on` (optional, time-boxed), `status`. Partners **never** appear in
  `Team Member`. The `fc_teams` resolver unions a user's member-grants **and**
  partner-grants but **tags each entry's `source`** (`member` | `partner`), so
  the path is always visible and separately revocable. One resolver, two
  explicit grant tables — still a single source per grant, no hidden path.
- **Option B: a dedicated partner role namespace + a flag on the grant** — same
  idea, lighter, if a full second DocType is overkill early.

Whichever you pick: a partner's access is **only** ever via the partner grant —
never by quietly adding them as a `Team Member`. Document the chosen path in
`spec/06`.

## Scope of work (Phases 1–3 of spec/10)

### Phase 1 — the bare data model (THIS is the first deliverable; stop here for review)

Create the **new Central app** with **only** the IAM DocTypes and their
predefined records. **No Python logic, no enforcement, no `seed_iam`** — records
ship as **fixtures**.

DocTypes (exactly these; structures in `spec/06`):
`Team`, `Team Member` (child), `Team Role`, `Role Capability` (child),
`Capability`. Set `track_changes` on `Team`, `Team Role` (auditability). `Team
Member.role` and `Role Capability.capability` are required Links.

Records to ship as **fixtures** (in `hooks.py`: `fixtures = ["Capability",
{"dt": "Team Role", "filters": [["is_system", "=", 1]]}]` — child `Role
Capability` rows travel with their parent Team Role):

- **Capability catalog** (the single source of "what actions exist"):
  - central plane: `team:edit`, `team:manage_members`, `team:delete`,
    `billing:view`, `billing:manage`, `asset:view`
  - atlas plane: `vm:create`, `vm:start`, `vm:stop`, `vm:resize`,
    `vm:terminate`, `vm:view`
- **System Team Roles** (`is_system = 1`, `team` = null), each = a bundle of the
  above:

  | Role | Capabilities |
  |---|---|
  | **Owner** | *all of them* |
  | **Admin** | `team:edit`, `team:manage_members`, `asset:view`, all `vm:*` |
  | **Developer** | `asset:view`, `vm:create/start/stop/resize/terminate/view` |
  | **Viewer** | `asset:view`, `vm:view` |
  | **Billing** | `billing:view`, `billing:manage`, `asset:view`, `vm:view` |

Create these by hand in the Desk UI (developer_mode exports the JSON/fixtures for
you), then confirm a fresh `bench --site <site> migrate` on a clean site
re-creates every record from the fixtures alone. **That clean re-create from
fixtures is the Phase-1 done bar** — no other behaviour yet.

> Custom (non-system) roles are simply `Team Role` rows with `team` set and
> `is_system = 0`; they are **not** fixtures and are the rare ~10% case. Nothing
> special to build for them — the model already allows them.

### Phase 2 — claim + audit (after Phase 1 is approved)

- A **resolver** (`user, team → grants`) reading only the canonical chain, and a
  small **audit view** ("effective permissions for user X", "members of team Y").
- The `fc_teams` token claim, reflecting **both** member and partner grants
  (tagged by `source`). Keep it bounded/small.
### Phase 3 — Atlas capture + enforce (the real cross-plane work)

   - Capture `fc_teams` from the SSO userinfo into the Atlas **session** at login.
   - Add the nullable `team` field to Atlas `Virtual Machine`; stamp it on create
     from the team-in-path, gated by `can("vm:create", team)`.
   - **Team-in-path routing** (`/dashboard/t/<team>/…`) + the **deep-link
     `redirect-to` fix** in Atlas `www/dashboard.py`.
   - Gate each whitelisted lifecycle method (`start/stop/resize/terminate/
     provision`) on the session's caps for the relevant team (VM's `team` for
     existing VMs; path team for create). One small `require_cap()` helper.
   - Replace Atlas's `owner_only` list query with team-scoped query conditions.

## Security gaps to close (these finish the design — see the architecture review)

- **Revocation freshness.** As-built, `fc_teams` is captured once into a long-
  lived Atlas session, so a revoked role could persist for days. **Bind freshness
  to a short clock**: prefer a short Atlas session forcing periodic *warm* re-SSO
  (which re-reads `fc_teams`), or a scheduled refresh. State the chosen bound.
- **Scope the registry service account** down from `System Manager` to a
  **read-only role on `Virtual Machine`** (the bootstrap over-privileged it).
- **Note HTTPS** as a production requirement for the token/userinfo channel
  (local POC is http).

## Implementation style (important)

- **Use the browser.** Create DocTypes, fields, system Roles, and Capability/
  Role records **directly in the Frappe Desk UI** where that's clearer than
  hand-writing JSON (developer_mode exports the JSON for you). **Don't hard-wire
  what should be data** — capabilities and roles are seeded records, not constants
  buried in code.
- **Verify in the running app, as real users.** Sites and demo creds are in
  `memory/central-atlas-local-setup.md`. Create a **second user with a non-Admin
  role** and prove, in the browser, that: a Viewer can't terminate; a Developer
  can; team A's member can't see team B's VMs; opening a VM lands on the exact
  machine after SSO. Don't claim done without exercising the dashboard.
- **Simple and effective.** Frappe-native first; smallest change that satisfies
  the principles. No new services, no crypto, no caching layers beyond the
  session. If you're tempted to add machinery, re-read principle 5.
- **Tiny steps.** Each plan step compiles, migrates, and is verifiable on its own.
  Keep Atlas's footprint minimal and its standalone (plain-session) operation
  intact.

## Advanced (optional) layer — finer scoping via Resource Groups

Build the core RBAC above **first** and verify it. Then, *only if asked*, add
finer-than-team scoping. **Do it the bounded, industry-standard way — scope by
group, never per-individual-VM ACLs** (per-VM ACLs are unbounded, un-auditable,
and breed allow/deny precedence — exactly the press mess to avoid). Design is in
`spec/06` ("Optional: finer scoping via Resource Groups"); the shape:

- A **`Resource Group`** DocType (a named bucket inside a team); each VM belongs
  to one group via a `resource_group` field (on the Central registry VM **and**
  Atlas's VM, stamped/synced like `team`). No group ⇒ team-wide default.
- **Scope is an attribute of the existing grant, not a new path.** A `Team Member`
  grant gains an optional `scope` = `*` (whole team) or a Resource Group. A member
  may hold multiple grants (e.g. `Viewer` team-wide + `Developer` on `staging`).
  **Reuse the predefined roles** — scoping is orthogonal; do not invent per-scope
  roles.
- **Allow-only, no deny rules.** "terminate vm-9 but not vm-10" = put them in
  different groups; absence of a covering grant = denied. Preserves single-source,
  auditability, and zero precedence logic.
- **Token stays bounded:** `fc_teams[team]` is a short **list** of
  `{role, caps, scope}` grants (common case: one grant, `scope:"*"` — unchanged).
  Enforce in Atlas: allow iff some grant has the cap and (`scope=="*"` or
  `scope == vm.resource_group`). Still a local session lookup, no Central call.
- **Single-VM granularity**, if ever truly needed, = a group with one VM. Stay in
  the group model.

This layer is **additive**: it must not change the team-wide default path, and a
team that creates no Resource Group must see none of it. Treat it as the rare
~10% — keep the UI for it secondary.

## Out of scope (do not build)

A Bench permission layer; billing enforcement; registry event-push / websockets;
a published `frappe-cloud-ui` package. (All deferred with triggers in `spec/10`.)

## Definition of done

- The information hierarchy and predefined roles exist as **data**, seeded
  idempotently; custom roles are possible but clearly the exception.
- A user's permissions resolve from **one** chain; an **audit view** can list
  "who can do what" and "who granted it" from records alone.
- Partner access is a **separate, tagged, independently-revocable** path.
- Atlas **enforces** caps end-to-end (gated lifecycle methods + team-scoped list),
  reading only the session — verified in the browser with multiple roles/teams.
- Revocation freshness is bounded by a stated short clock; the service account is
  read-only; HTTPS noted for prod.
- `spec/06` (and `spec/10` status) updated to match what you actually built.
