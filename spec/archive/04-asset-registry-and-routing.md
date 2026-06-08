# 04 — Asset Registry & Routing

The registry is Central's reason to exist: **one global, eventually-consistent
list of everything a user owns across every cluster**, plus the routing that
takes them into any of it.

## Where the data comes from (W2 — sync)

Atlas exposes a standard Frappe REST API and **no event push** today, so Central
**pulls**. A scheduled job (and an on-demand "Sync now") iterates `Active`
clusters and, for each, calls Atlas's REST API as the service account:

```
GET {cluster.base_url}/api/method/frappe.client.get_list
    ?doctype=Virtual Machine
    &fields=["name","title","status","plan_id","ipv6_address",
             "vcpus","memory_megabytes","disk_gigabytes","owner","modified"]
    &limit_page_length=0
  Authorization: token {cluster.api_key}:{cluster.api_secret}
```

For each returned VM, Central **upserts** a `Virtual Machine` registry row keyed by
(`cluster`, `vm_id`):
- maps `owner` email → Central User → Team (see `spec/02` ownership mapping),
- copies catalog fields,
- sets `last_synced = now`.

VMs present last sync but absent now are marked `archived` (tombstone, not hard
delete). Sync errors are recorded on `Cluster.last_sync_error` and the cluster's
rows simply go stale — they are **not** removed.

> **Sync cadence:** every 2–5 min scheduled, plus on-demand. This is an
> eventually-consistent index, exactly like AWS's resource inventories. Identity
> changes slowly; that lag is acceptable. *Live* state is handled separately ↓.

### Future: flip to push
When Atlas grows callbacks, it will `POST` lifecycle events
(`vm.created`/`vm.updated`/`vm.terminated`) to a Central ingest endpoint. The
upsert logic and the registry schema are unchanged; only the trigger changes from
poll to push. Design W2 so the upsert is a single idempotent function callable
from either path.

## Live status (W4 — read-through, lazy)

The list renders **from registry rows** (fast, always available). Live power state
is fetched **after** render, per visible row, in parallel:

```
SPA → Central: GET /api/method/central.api.get_vm_status?vm=<name>
Central → Atlas: GET {base_url}/api/method/frappe.client.get_value
                   ?doctype=Virtual Machine&filters={"name":"<vm_id>"}&fieldname="status"
Central: cache in Redis 30–60s, update status_cached/status_synced_at, return.
```

Rules (from the blast-radius principle):
- Lazy and per-row; never blocks the initial list paint.
- Each request independent and cancellable; a dead cluster yields
  `status: "unavailable"` for *its* rows only.
- Cached 30–60s so repeated views don't hammer clusters.

## Routing on select (W3 — the hand-off)

Selecting a registry row routes the user **into the owning cluster's Atlas**, on
the exact page for that asset. The full SSO mechanics are in `spec/03`; from the
registry's point of view:

- **Click a VM row → "Open"** ⇒ navigate to
  `{cluster.base_url}/dashboard/machines/{vm_id}`.
- **"Open cluster console"** (from a cluster header/filter) ⇒ navigate to
  `{cluster.base_url}/dashboard/machines`.
- Navigation is a full `window.location` redirect (cross-domain), which triggers
  the OAuth2 SSO if no Atlas session exists yet.

Central does **not** open Atlas in an iframe or proxy its API for operations —
hand-off over integration.

## API surface (Central)

Standard Frappe REST + a couple of thin methods:

| Endpoint | Purpose |
|---|---|
| `GET /api/method/frappe.client.get_list` (DocType `Virtual Machine`) | The registry list (permission-scoped to the user's teams) |
| `GET /api/method/central.api.get_vm_status?vm=<name>` | W4 live status read-through (cached) |
| `POST /api/method/central.api.sync_cluster?cluster=<name>` | On-demand W2 sync (admin) |

Row-level visibility is enforced server-side with `permission_query_conditions` /
`has_permission`: a user sees only `Virtual Machine` rows whose `team` is one of
their teams. (Same pattern Atlas uses to scope VMs to their owner.)
