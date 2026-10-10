# Capability Taxonomy

Capabilities are the authorization vocabulary of the Frappe Cloud control plane. Central is the source of truth. It resolves a user's team grants into capability strings and enforces them before every regional or Pilot call.

The capability set lives in [`fixtures/capability.json`](central/fixtures/capability.json) and the default role assignments in [`fixtures/team_role.json`](central/fixtures/team_role.json). This document is the human-readable reference for that data.

A capability is named `resource:action` and belongs to exactly one **plane**:

| Plane | Owner | Enforced in |
| --- | --- | --- |
| `central` | Central | Central (`central/permissions.py`, Team doc methods) |
| `atlas` | Atlas | Central, before each regional call (`central/utils/guards.py`, `central/iam.py`) |
| `bench` | each bench | No capabilities on this plane today |

## Server is the atomic unit (model v5)

Role capabilities live at the **team** and **server** level only. A team manages servers, and a server is a bench host. The **bench plane** holds no capabilities. Bench tokens carry no capabilities today. The `bench` plane value stays on Capability, so site-level capabilities can return under it later. `asset:view` is not a capability, because `server:view` gates the Virtual Machine registry.

## Vocabulary vs. roles

The distinction matters:

- **The vocabulary** is the set of capability strings below. Central enforces it, and stored grants, fixtures, and the dashboard depend on it. It is small and changes rarely.
- **Roles** (system roles and team-defined custom roles) are named subsets of that vocabulary. A custom role recombines existing capabilities. It never mints a new capability string. Teams can create as many custom roles as they like without an effect on this contract.

## The 16 capabilities

### `central` plane (8)

| Capability | Meaning |
| --- | --- |
| `billing:view` | View billing data. |
| `billing:manage` | Manage billing settings and payment operations. |
| `team:edit` | Edit team metadata. |
| `team:manage_members` | Invite, suspend, and change team members. |
| `team:delete` | Delete a team. |
| `service:view` | View managed service configuration. |
| `service:manage` | Create and delete storage buckets, set bucket quotas, rotate bucket credentials, and download stored objects. |
| `server:ssh-key` | Add, rotate, and remove Team SSH keys for selected servers. |

### `atlas` plane (8)

| Capability | Meaning |
| --- | --- |
| `cluster:view` | View clusters the team can place servers in. |
| `server:view` | List and open servers and sites; view status, specs, and metrics. |
| `server:create` | Provision a new server. |
| `server:power` | Start, stop, and restart a server. |
| `server:resize` | Resize, rebuild, or rename a server. |
| `server:snapshot` | Create and restore server snapshots. |
| `server:terminate` | Destroy a server. |
| `server:console` | Open the web console of a running server. |

### `bench` plane (0)

No capabilities are seeded on the bench plane in v5. Site-level management capabilities, such as `site:view`, `site:create`, or `site:apps`, would go here. Adding one needs an agreed bench token contract with Pilot first.

## Capability implications

Acting on a resource is meaningless without seeing it. Central closes every grant under these implications before it asserts or evaluates the grant ([`central/iam.py`](central/iam.py)):

| Capability | Implies |
| --- | --- |
| `server:create` | `server:view`, `cluster:view` |
| `server:power` / `resize` / `snapshot` / `terminate` | `server:view` |
| `server:ssh-key` | `server:view` |
| `server:console` | `server:view` |
| `service:manage` | `service:view` |

The role builder can let a user tick `server:create` without `server:view` and `cluster:view`. A grant made directly through the API cannot bypass the closure either.

## Scoped grants

A role grant can apply to one server or site instead of the whole team. A scoped grant carries only these capabilities, on that server: `server:view`, `server:power`, `server:resize`, `server:snapshot`, `server:terminate`, and `server:console`. Every other capability is team-wide and comes only from a team-wide grant. For example, Developer on one server can stop that server, but cannot create a server or change the Team SSH keys. See [IAM resource scope](spec/IAM.md#resource-scope).

## The 5 system roles

System roles are seeded from `fixtures/team_role.json` and are identical across all teams. Teams may also define custom roles scoped to themselves.

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
| `server:ssh-key` | ✓ | ✓ | ✓ | | |
| `server:terminate` | ✓ | ✓ | ✓ | | |
| `server:console` | ✓ | ✓ | ✓ | | |
| `service:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `service:manage` | ✓ | ✓ | ✓ | | ✓ |

Totals: Owner 16, Admin 15, Developer 11, Viewer 3, Billing 6.

The ladder reads top to bottom: **Viewer** (look), **Billing** (look and pay), **Developer** (operate servers), **Admin** (Developer and run the team), **Owner** (Admin and delete the team). A team has exactly one Owner, transferable through Transfer Ownership. For a different mix, such as server operations without billing, create a custom role.

## Changing the taxonomy

Stored grants, fixtures, and the dashboard depend on the vocabulary. Adding, removing, or renaming a capability is a coordinated change:

1. Edit the fixtures (`fixtures/capability.json`, `fixtures/team_role.json`) and run `bench export-fixtures --app central` to regenerate them from the DB.
2. Bump `CAPABILITY_VERSION` in `central/iam.py` to record the taxonomy revision.
3. Add a migration patch to delete removed records. Fixture sync only upserts. It never deletes.
4. Update this document.

**Never rename a capability in place.** Stored grants and every consumer keep the old string, and the result authorizes the wrong thing without an error. Add the new capability, migrate grants to it, then retire the old one.
