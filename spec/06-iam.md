# 06 — IAM (Identity, Teams, Roles & Permissions)

This spec is the authoritative model for **identity, teams, roles, and
permissions** across Central (authority) and Atlas (enforcement) — the IAM layer
being shipped.

> **Scope (v1):** two planes only — **Central authors, Atlas enforces**. Bench
> has **no permission layer**; everything a user does is a VM-level action
> enforced by Atlas. Per-individual-VM permissions and a Bench permission layer
> are explicitly future.

## First principles

1. **Identity is global and singular.** A person is one `User` in Central. They
   never have a second password anywhere. Atlas holds only a *shadow* identity
   (a mirror keyed by the Central identity) — never credentials.

2. **Ownership and permission attach to a Team, not a person.** Assets outlive
   employees. A user acts *as a team*; what they may do is a function of their
   **role in that team**, not of their personal account.

3. **Central is the sole author of permissions; Atlas only enforces.** Roles,
   capabilities, and team membership are defined, granted, and revoked **only**
   in Central. Atlas has zero permission-editing logic — it never invents or
   changes a permission. It only reflects and enforces what Central decided.

4. **The OAuth token *is* the permission channel — we don't build a second
   one.** Central already signs short-lived OAuth/OIDC tokens that Atlas already
   verifies (`spec/03`). That is exactly — and only — what carrying permissions
   needs. So the user's capabilities ride **as a claim in the token**. No
   bespoke policy-mirror service, no push/pull sync, no signature scheme of our
   own, no version/expiry bookkeeping we invent. (Standard framework components
   first, `spec/01` #4.)

5. **Central is never in a region's synchronous path.** Atlas enforces from the
   **session** (the token's claims), not by calling Central per action. A
   Central outage therefore can't take a region down: existing sessions keep
   working until their token expires; only *new* logins fail (you can't mint
   authority while the authority is unreachable). This behaviour falls out of
   how OAuth already works — there is nothing extra to build.

## User signup and first team

Signup must leave the user with a complete, testable IAM graph. A Central user
with no team is an identity only; they cannot own assets and their `fc_teams`
claim is empty. So a normal signup creates the user's first team immediately.

Flow for a direct/self signup:

1. Frappe creates the `User` in Central.
2. Central assigns the native `Central User` role so the account can enter the
   Central Desk/app surface.
3. Central creates one personal/default `Team` for the user.
4. Central adds the same user to that team as a `Team Member` with the system
   `Owner` team role and `Active` status.
5. The user's next OAuth userinfo/ID-token generation resolves this membership
   into `fc_teams`, so Atlas receives a real team id and the Owner capability
   bundle.

This does **not** create a second permission path. The user is tied to the team
only by the `Team Member` row. `Team.owner_user` is legal/billing ownership
metadata and is kept consistent with the initial Owner member, but it is not an
authorization bypass.

Flow for an invited user is a future extension:

1. An invitation records `email -> team -> role`.
2. On signup/login, Central consumes the invite and creates the corresponding
   `Team Member` row.
3. If product wants every user to also have a personal team, Central can create
   that as a separate Owner membership. The invited-team grant still remains a
   normal `Team Member` row.

The implementation is a `User.after_insert` hook. Every enabled User created
after Central is installed is bootstrapped this way; install/migrate-time fixture
work is ignored so app setup stays deterministic.

## Data model (Central owns all of it)

### `Team` — the unit of ownership

| Field | Type | Notes |
|---|---|---|
| `name` (PK) | surrogate | **Not** email, **not** the display name. `naming_series = TEAM-.#####`. Stable forever. |
| `team_name` | Data | Human label, **freely editable** ("Acme Inc"). Display only — renaming never breaks links. |
| `owner_user` | Link → User | The billing/legal owner; exactly one. Transferable. |
| `status` | Select | `Active` / `Suspended`. |

> **Why a surrogate key:** keying a Team by email or by `team_name` means a
> rename or owner change rewrites the primary key and every foreign key
> (`Virtual Machine.team`, invoices, …). A surrogate `name` makes `team_name`
> and `owner_user` ordinary editable attributes. Non-negotiable.

### `Team Member` — who is in the team (child table of Team)

| Field | Type | Notes |
|---|---|---|
| `user` | Link → User | The person. Unique within the team. |
| `role` | Link → Team Role | The capability bundle. |
| `status` | Select | `Active` / `Invited` / `Suspended`. |

**Permissions are role-based, not user-based.** A member's effective
capabilities are **exactly their role's capabilities** — there are no per-user
grants or overrides. To change what someone can do, change their role. The
deliberate consequence: two members with the same role have identical powers;
if you need them to differ, give them different roles (or a narrow custom role).
This keeps "who can do what" answerable by looking at roles alone.

### `Team Role` — a named bundle of capabilities

| Field | Type | Notes |
|---|---|---|
| `name` | Data | Stable document id. System roles are named `Owner`, `Admin`, `Developer`, `Viewer`, `Billing`. |
| `role_name` | Data | Human label shown in Desk. |
| `is_system` | Check | System roles can't be edited/deleted. |
| `team` | Link → Team \| null | Null = global system role; set = a custom role private to one team. |
| `capabilities` | Table → Role Capability | The granted capability strings. |

System role bundles (assign a role, done):

| Role | Holds |
|---|---|
| **Owner** | everything, incl. billing + member management + team delete |
| **Admin** | all VM actions (create/start/stop/terminate/resize) + member management; not billing |
| **Developer** | `asset:view` plus all VM actions (`vm:create/start/stop/resize/terminate/view`); no team or billing management |
| **Viewer** | `asset:view`, `vm:view` |
| **Billing** | `billing:view`, `billing:manage`, `asset:view`, `vm:view` |

### `Capability` — the catalog of actions (seeded fixtures)

A flat, append-only vocabulary of `"<resource>:<verb>"` strings, tagged by the
plane that enforces it. **v1 has two planes only:**

| `name` | `plane` | `resource` |
|---|---|---|
| `team:edit`, `team:manage_members`, `team:delete`, `billing:view`, `billing:manage`, `asset:view` | central | team / billing / registry |
| `vm:create`, `vm:start`, `vm:stop`, `vm:resize`, `vm:terminate`, `vm:view` | atlas | virtual machine |

> "VM-level actions" means **action-type** granularity (start vs terminate). By
> default a member's role applies **uniformly across the team's VMs** — that's the
> 80–90% case. Finer scoping ("terminate these VMs but not those") is the optional
> **Resource Group** layer below — *not* per-individual-VM ACLs.

## Optional: finer scoping via Resource Groups (the rare ~10%)

A literal per-VM ACL (`{vm-9: terminate, vm-10: deny}`) is the wrong tool: it's
**unbounded** (can't ride in the token), **un-auditable** ("what can Dana do?"
means scanning every VM), and breeds allow/deny **precedence puzzles**. So we do
what every cloud does — **scope by group, put resources in groups** (AWS
tags/scoped policies, GCP projects, k8s namespaces+RoleBindings).

- **`Resource Group`** — a named bucket inside a team (`production`, `staging`,
  `client-acme`). Each VM belongs to **one** group (a `resource_group` field on
  the registry VM and on Atlas's VM, stamped/synced like `team`). No group = the
  team-wide default scope.
- **Scope is an attribute of the grant, not a new path.** `Team Member` keeps its
  role; it gains an optional **`scope`** = the whole team (default, `*`) or a
  Resource Group. A member may hold more than one grant (e.g. `Developer` on
  `staging`, `Viewer` team-wide). Roles are **reused** — scoping is orthogonal to
  the predefined role set, so it never multiplies roles.
- **Allow-only — no deny rules.** "Terminate vm-9 but not vm-10" = put them in
  different groups and grant on one. Absence of a covering grant = denied. This
  keeps a single source, full auditability, and zero precedence logic.
- **The token stays bounded.** `fc_teams[team]` is a short list of grants
  `[{role, caps, scope}]` — `scope` is `"*"` or a handful of group ids, never a
  VM list. The common case is exactly one grant with `scope:"*"` (today's shape).
- **Enforcement (Atlas):** for an action on vm-X, resolve `gid = vm-X.resource_group`;
  allow iff some grant has the capability **and** (`scope == "*"` or
  `scope == gid`). Still a local session lookup — bounded, no Central call.
- **True single-VM granularity** = a group containing one VM. Possible, but you
  stay inside the bounded group model.

This is a clean *additive* layer: the default team-wide grant is unchanged, and a
team that never creates a Resource Group never sees any of it.

## How the team is selected: team-in-path

Central's registry is the **only cross-team surface** — one list of everything
you own across every team and region. An **Atlas session is single-team**: the
active team is explicit in the URL, never in hidden session state.

- Atlas routes are **`/dashboard/t/<team>/machines/:name`**. Central builds the
  deep link and already knows the asset's team, so "open vm-9" →
  `…/t/<team-of-vm-9>/machines/vm-9` (no ambiguity); "create" / "console" →
  Central shows a team picker and the choice becomes `<team>` in the path.
- Atlas authorizes **per request against the team in the path** — never against
  implicit session state, which removes the "operated under the wrong team"
  foot-gun by construction.
- **Switching team is just navigation** to `…/t/<other-team>/…` — no re-handoff
  needed, because the token already carries every team's capabilities (below).

## What's in the token (the whole mechanism)

At hand-off, Central issues the OIDC token with identity **plus a bounded map of
the user's teams → role + capabilities**. A user belongs to a handful of teams,
so the claim is small:

Each team maps to a **short list of grants** `{role, caps, scope}`. The common
case is a single grant scoped to the whole team (`scope: "*"`); Resource-Group
scoping (above) just adds more grants with a group id as `scope`:

```jsonc
// OIDC claim, set by Central at authorize/userinfo time
{
  "sub": "dana@acme.com",
  "fc_teams": {
    "TEAM-00042": [ { "role": "Admin",  "scope": "*",         "caps": ["vm:create","vm:start","vm:stop","vm:terminate","vm:resize","vm:view"] } ],
    "TEAM-00099": [ { "role": "Viewer", "scope": "*",         "caps": ["vm:view"] },
                    { "role": "Developer", "scope": "RG-staging", "caps": ["vm:start","vm:stop","vm:resize","vm:view"] } ]
  }
}
```

- The **path picks the team**; the token supplies that team's **grants**. So team
  selection (path) and capabilities (token) compose cleanly.
- **Bounded:** grants per team = (1 + number of group-scoped exceptions), never a
  per-VM list.
- **Central resolves role → caps** before minting the claim, so Atlas never
  needs to know role *definitions* — only the resolved caps travel. Custom roles
  work with zero Atlas changes.
- **Staleness is bounded by the token lifetime** (e.g. 15 min). Revoke Dana or
  change her role in Central → her next token refresh reflects it. The token's
  own expiry *is* the freshness bound; there is nothing else to expire.

## Central implementation slice

The current Central app implements the authority side only:

- Desk DocTypes: `Team`, `Team Member`, `Team Role`, `Role Capability`,
  `Capability`, and `IAM Permission Probe`.
- Fixtures: `Capability`, system `Team Role`s, and native `Central User`.
  `Capability` remains the append-only action catalog; role bundles are data,
  not code constants.
- User bootstrap: a new enabled non-system `User` receives `Central User`, one
  default `Team`, and an active `Owner` membership in that team.
- Resolver: `central.iam.resolve_user_grants(user)` reads only the canonical
  chain `Team Member -> Team Role -> Role Capability -> Capability`.
- OAuth layer: Central patches Frappe's OpenID userinfo generation to include
  `fc_teams` in both the userinfo path and the ID-token generation path used by
  Frappe's OAuth validator. The patch is isolated in `central.oauth` because the
  local Frappe version does not expose a first-class custom-claim hook.
- Audit/test surface: `IAM Permission Probe` and `central.api` expose effective
  grants and a yes/no capability check for a `(user, team, capability)` tuple.
- Desk row scoping: `Central User` can read only teams they actively belong to
  and system roles plus custom roles for those teams. `System Manager` is the
  sole operator bypass and is implemented in one resolver function.

Atlas frontend and enforcement are intentionally not part of this slice. Atlas
still needs to capture `fc_teams` into session state, add `Virtual Machine.team`,
move to team-in-path routes, and gate lifecycle methods locally.

## Enforcement (the Atlas contract)

Atlas's VM lifecycle methods are already separate whitelisted endpoints
(`provision` / `start` / `stop` / `terminate` / `resize`). Each gates on the
session's caps for the path's team — one line apiece:

```python
def can(action: str, team: str, group: str | None = None) -> bool:
    grants = frappe.session.oauth_claims["fc_teams"].get(team) or []   # token → session
    # allow iff some grant has the cap AND its scope covers this VM's group
    return any(
        action in g["caps"] and (g["scope"] == "*" or g["scope"] == group)
        for g in grants
    )

# in terminate():  group is the VM's own resource_group ("*"-covered if None)
if not can("vm:terminate", self.team, self.resource_group):
    frappe.throw("Not permitted", frappe.PermissionError)
```

When a team uses no Resource Groups, every grant is `scope: "*"` and the `group`
argument is ignored — i.e. the default path is unchanged.

- **List scoping** at `/dashboard/t/<team>/machines` filters to that team's VMs
  (`team` is the path value; the user is a member iff the token has that team).
- **Create** stamps `Virtual Machine.team = <path team>` only after `can(
  "vm:create", team)` passes — so the team attribution is **trustworthy by
  construction** (it was authorized by a Central-signed token). If/when an asset
  registry mirrors VMs into Central (a separate concern, out of scope for the IAM
  layer), it reads this `team` back and trusts it with a cheap existence check.
- **Atlas Virtual Machine gains a nullable `team` field** (Central's surrogate
  `Team.name`, stored as opaque data Atlas never interprets) — the one new
  Atlas field this model requires.

## Relationship to Frappe's native roles & permissions

We reuse the framework for what it's good at and add our layer only for what it
structurally can't express. Complementary, not competing.

**Reused natively:**

| Frappe primitive | Its job here |
|---|---|
| `User` + login / 2FA / social login | Identity (`spec/03`). |
| Site-level `Role` (`System Manager`, `Central User`, `Atlas User`) | The coarse staff-vs-customer / app-access gate. The operator short-circuit (`System Manager` ⇒ unrestricted) is native-role reuse. |
| `DocPerm` (role → doctype → CRUD, `permlevel`) | Baseline "can this audience touch this doctype at all" + field-level hiding. |
| `permission_query_conditions` + `has_permission` hooks | The **enforcement mechanism** for team row-scoping on the Central side. |

**Cannot be native `Role`s — and why:**
1. **Roles are user-global; our authority is per-(user, team).** Dana is Admin
   in Acme *and* Viewer in Beta — inexpressible as a site Role. ⇒ `Team
   Member.role` is ours.
2. **DocPerm's axis is CRUD-per-doctype; ours is verb-per-action.** `vm:start` /
   `vm:terminate` are both "call a method on `Virtual Machine`" to Frappe — no
   native "permission to run *this* whitelisted method." ⇒ capabilities are ours,
   checked inside the method.

> **The trap:** do **not** make `Team Owner` / `Team Admin` native Frappe Roles —
> a native role is global, so a user who admins one team would admin *every*
> team. Team authority lives in `Team Member.role`, never in the site role list.
> (`press` itself went custom for exactly this reason.)

## Worked example — "may Dana terminate `vm-9`?"

1. Dana opens `bangalore/dashboard/t/TEAM-42/machines/vm-9` (Central built the
   URL; it knows vm-9's team).
2. Atlas reads `fc_teams["TEAM-42"]` from her session token: role `Admin`,
   caps include `vm:terminate`. ⇒ allowed, enforced **locally**, no call to
   Central.
3. If Dana were `Operator`, the caps wouldn't include `vm:terminate` ⇒ refused.
4. If she'd been removed from Acme, her next token wouldn't contain `TEAM-42`
   ⇒ refused within one token lifetime; an existing token works until it expires.

## Build order

- **v1a — the bare data model (build this first, on a fresh app):** just the five
  DocTypes (`Team`, `Team Member`, `Team Role`, `Role Capability`, `Capability`)
  and their predefined records — the capability catalog + the system roles
  (Owner/Admin/Developer/Viewer/Billing) — shipped as **fixtures**, *not* an
  imperative seed function. No resolver, no claim, no enforcement code yet. Done
  bar: a clean `bench migrate` re-creates every record from fixtures alone.
- **v1b — make it enforce (the 80–90%):** the resolver + `fc_teams` token claim
  (grants list, all `scope:"*"`); Atlas gates its lifecycle methods on it; Atlas
  gains the `team` field + team-in-path routing. Most teams never need more.
- **v2 (the rare 10%, additive):** custom team-scoped roles; **Resource Groups**
  + scoped grants (the `resource_group` field on the VM, `scope` on the grant,
  the grant-list in the token). Layered cleanly on v1 — a team that makes no
  group never sees it.
- **Later:** a Bench permission layer (`spec/10`).
