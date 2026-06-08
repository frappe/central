# 02 — Data Model

v1 DocTypes only. Each owns exactly one fact (see `spec/README` principle 1).
Frappe's built-in `User` is reused unchanged for authentication.

## Ownership: `Team` and `Team Member`

Ownership and (later) billing attach to **Teams**, not individual users — a user
may belong to several teams, and assets outlive any one person.

### `Team`
| Field | Type | Notes |
|---|---|---|
| `team_name` | Data | Display name, e.g. "Acme Inc" |
| `owner_user` | Link → User | The creating/owning user |
| `status` | Select | `Active` / `Suspended` (default `Active`) |

> v1 keeps Teams minimal. Invites, billing profiles, and roles-per-asset are
> future. Every user gets a personal Team on signup (one-member team).

### `Team Member`
| Field | Type | Notes |
|---|---|---|
| `team` | Link → Team | |
| `user` | Link → User | |
| `role` | Select | `owner` / `admin` / `member` / `viewer` (default `member`) |

Unique on (`team`, `user`).

## Cluster directory: `Cluster`

One row per Atlas instance. This is **W1** — how Central knows a region exists and
how to reach and authenticate to it.

| Field | Type | Notes |
|---|---|---|
| `cluster_name` | Data | Display name, e.g. "Bangalore" |
| `region` | Data | Slug, e.g. `bangalore` |
| `base_url` | Data | e.g. `https://bangalore.x.frappe.dev` (no trailing slash) |
| `status` | Select | `Active` / `Draining` / `Offline` (default `Active`) |
| `api_key` | Data | Atlas API key for W2/W4 server-to-server calls |
| `api_secret` | Password | Atlas API secret (encrypted at rest) |
| `oauth_client_id` | Data | This cluster's OAuth2 client id (issued by Central — see `spec/03`) |
| `last_synced` | Datetime | Set by W2 sync job |
| `last_sync_error` | Small Text | Last sync failure message, if any |

Derived helpers (not stored): a VM's deep link is
`{base_url}/dashboard/machines/{vm_id}`; a cluster's console is
`{base_url}/dashboard/machines`.

## Asset registry: `Virtual Machine`

Central's mirror of an Atlas VM. **Identity and ownership only.** Runtime status is
*cached* (W4), never authoritative.

| Field | Type | Notes |
|---|---|---|
| `vm_id` | Data | **Atlas's `name`/UUID** — the join key. Unique with `cluster`. |
| `title` | Data | Human label from Atlas |
| `cluster` | Link → Cluster | Which region it lives in |
| `team` | Link → Team | Owning team (see ownership mapping below) |
| `plan_id` | Data | Opaque plan identifier from Atlas (Central does not interpret it in v1) |
| `vcpus` | Int | Catalog info, synced |
| `memory_megabytes` | Int | Catalog info, synced |
| `disk_gigabytes` | Int | Catalog info, synced |
| `ipv6_address` | Data | Synced |
| `status_cached` | Select | `Running` / `Stopped` / `Pending` / `Failed` / `Unknown` — last seen (W4); display-only |
| `status_synced_at` | Datetime | When `status_cached` was last refreshed |
| `last_synced` | Datetime | When the identity row was last synced (W2) |
| `archived` | Check | Soft-delete tombstone; hidden from default list |

**Naming:** Central's `Virtual Machine.name` (PK) = `{region}-{vm_id}` to guarantee
global uniqueness across clusters.

**Ownership mapping (v1):** Atlas scopes a VM to an owner user (the "Atlas User"
role). During W2 sync, Central maps that owner's email → a Central User → that
user's personal Team. Assets whose owner can't be mapped are parked under a
`status = Unassigned` system team and surfaced to admins. Richer ownership
(explicit team assignment, shared access rules) is future.

> **Extensibility:** when Atlas grows `Site`/`App`, add sibling registry DocTypes
> (`Site`, `App`) with the same shape (`{x}_id`, `cluster`, `team`, cached status).
> The list view (`spec/05`) is written against a normalized "asset" projection so
> new types appear as new rows, not new screens.

## What Central deliberately does NOT store

- Live CPU/memory/disk *usage* metrics (regional, ephemeral).
- Authoritative VM power state (only a short-lived cache).
- SSH keys, server inventory, Firecracker config, images, snapshots — all Atlas.
- Anything about sites/apps/bench — not yet exposed by Atlas.
- Prices, invoices, usage records — billing is out of scope for v1.
