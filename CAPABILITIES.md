# Capability Taxonomy

Capabilities are the authorization vocabulary of the Frappe Cloud control plane.
Central is the source of truth: it resolves a user's team grants into capability
strings and stamps them into the SSO token (`fc_teams` claim). Atlas and each
bench then enforce those strings on their own resources.

The capability set lives in [`fixtures/capability.json`](central/fixtures/capability.json)
and the default role assignments in [`fixtures/team_role.json`](central/fixtures/team_role.json).
This document is the human-readable reference for that data.

A capability is named `resource:action` and belongs to exactly one **plane**:

| Plane | Owner | Enforced in |
| --- | --- | --- |
| `central` | Central | Central (`central/permissions.py`, Team doc methods) |
| `atlas` | Atlas | Atlas API (when wired) |
| `bench` | each bench | bench `admin/backend/auth.py` (`BENCH_CAPS`) |

## Server is the atomic unit (model v3)

Role capabilities live at the **team** and **server** level only. A team manages
servers; a server *is* a bench host. The **bench plane** — site-level capabilities
plus the bench-internal `server:config` — is **deferred**: the plane, the
`bench`-caps SSO mint, and the implication map all remain, so site capabilities can
return under the bench plane later with no change to the token contract or to any
deployed bench. `asset:view` was dropped as redundant — the Asset registry is gated
on `server:view`.

## Vocabulary vs. roles

The distinction matters:

- **The vocabulary** — the capability strings below — is the part that crosses
  into a bench's token and gets enforced. It is small and changes rarely.
- **Roles** (system *and* team-defined custom roles) are just *named subsets* of
  that vocabulary. A custom role recombines existing capabilities; it never mints
  a new capability string, so a bench always understands the result. Teams can
  create as many custom roles as they like without affecting this contract.

## The 15 capabilities

### `central` plane (7)

| Capability | Meaning |
| --- | --- |
| `billing:view` | View billing data. |
| `billing:manage` | Manage billing settings and payment operations. |
| `team:edit` | Edit team metadata. |
| `team:manage_members` | Invite, suspend, and change team members. |
| `team:delete` | Delete a team. |
| `service:view` | View the team's add-on services (LLM, storage). |
| `service:manage` | Provision and manage add-on services and their credentials. |

### `atlas` plane (8)

| Capability | Meaning |
| --- | --- |
| `cluster:view` | View clusters the team can place servers in. |
| `server:view` | List servers; view status, specs, and metrics. |
| `server:create` | Provision a new server. |
| `server:power` | Start, stop, and restart a server. |
| `server:resize` | Resize or rebuild a server. |
| `server:snapshot` | Create and restore server snapshots. |
| `server:terminate` | Destroy a server. |
| `server:open` | Open a server's console (bench admin) via signed-token SSO. |

### `bench` plane (0 — deferred)

No capabilities are seeded on the bench plane in v3. When site-level management
returns (e.g. `site:view`, `site:create`, `site:apps`, …) it slots in here and
flows into the bench token through the existing `sso._bench_caps` filter unchanged.

## Capability implications

Acting on a server is meaningless without seeing it, so every grant is closed
under these implications before it is asserted or evaluated
([`central/iam.py`](central/iam.py)):

| Capability | Implies |
| --- | --- |
| `server:open` | `server:view` |
| `server:create` | `server:view`, `cluster:view` |
| `server:power` / `resize` / `snapshot` / `terminate` | `server:view` |
| `service:manage` | `service:view` |

The role builder can let a user tick `server:create` without remembering
`server:view`/`cluster:view`, and a grant hand-crafted through the API cannot
bypass the closure either.

## The 5 system roles

System roles are seeded from `fixtures/team_role.json` and are identical across
all teams. Teams may also define custom roles scoped to themselves.

| Capability | Owner | Admin | Developer | Viewer | Billing |
| --- | :-: | :-: | :-: | :-: | :-: |
| `team:edit` | ✓ | ✓ | | | |
| `team:manage_members` | ✓ | ✓ | | | |
| `team:delete` | ✓ | | | | |
| `billing:view` | ✓ | ✓ | | | ✓ |
| `billing:manage` | ✓ | ✓ | | | ✓ |
| `cluster:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `server:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `server:create` | ✓ | ✓ | ✓ | | |
| `server:power` | ✓ | ✓ | ✓ | | |
| `server:resize` | ✓ | ✓ | ✓ | | |
| `server:snapshot` | ✓ | ✓ | ✓ | | |
| `server:terminate` | ✓ | ✓ | ✓ | | |
| `server:open` | ✓ | ✓ | ✓ | | |
| `service:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `service:manage` | ✓ | ✓ | ✓ | | ✓ |

Totals: Owner 15, Admin 14, Developer 10, Viewer 3, Billing 6.

The ladder reads top to bottom: **Viewer** (look) → **Billing** (look + pay) →
**Developer** (operate servers) → **Admin** (Developer + run the team) → **Owner**
(Admin + delete the team). A team has exactly one Owner, transferable via Transfer
Ownership. Need a different mix (e.g. server operations without billing)? Create a
custom role.

## Changing the taxonomy

The vocabulary is a contract with every deployed bench, so adding, removing, or
renaming a capability is a coordinated change, not a casual one:

1. Edit the fixtures (`fixtures/capability.json`, `fixtures/team_role.json`) and
   run `bench export-fixtures --app central` to regenerate them from the DB.
2. Bump `CAPABILITY_VERSION` in `central/iam.py` (stamped into the SSO assertion so
   a bench can detect drift from its `BENCH_CAPS` mirror).
3. Add a migration patch to delete removed records — fixture sync only upserts, it
   never deletes (see `central/patches/v03_strip_to_server_caps`).
4. Update the `bench`-plane mirror (`BENCH_CAPS` and the route→capability map in
   `admin/backend/auth.py`) if a `bench`-plane capability changed.
5. Update this document.

**Never rename a capability in place.** An already-deployed bench keeps checking
the old string and will authorize the wrong thing, silently. Add the new
capability, migrate grants to it, then retire the old one.
