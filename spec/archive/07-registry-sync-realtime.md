# 07 — Asset Registry: Sync, Cache & "Realtime"

`spec/04` established *what* the registry is and the four wires. This spec
drives out the implementation. The guiding rule here is **keep it simple** —
the registry needs exactly two mechanisms, and the heavier machinery (incremental
sync, event push, websockets) is a *scale* optimization documented for later,
not built now.

## First principles

1. **The registry is a cache of identity, not a second source of truth.** Atlas
   owns the fact that `vm-9` exists. Central mirrors it so the global list is
   instant and survives a region outage. When they disagree, **Atlas wins**.

2. **Two clocks, never conflated.** *Identity* (exists / who owns it / specs)
   changes slowly — minutes of lag is fine. *Power state* (running/stopped)
   changes fast and must look live. They are handled by two different,
   independent mechanisms below.

3. **One idempotent upsert.** `upsert_vm(cluster, payload)` is the single write
   path. Today only one thing calls it (the periodic pull); if push is ever
   added, it calls the same function. The write logic never changes.

## The model (all of it)

### Identity — a periodic full pull (W2)

A scheduled job iterates `Active` clusters and, for each, pulls the **full** VM
list as the service account and upserts:

```
GET {base_url}/api/method/frappe.client.get_list
    ?doctype=Virtual Machine
    &fields=["name","title","status","plan_id","ipv6_address","vcpus",
             "memory_megabytes","disk_gigabytes","team","owner","modified"]
    &limit_page_length=0
  Authorization: token {api_key}:{api_secret}
```

For each returned VM, `upsert_vm`:
- keys on `(cluster, vm_id)` → registry `name = {region}-{vm_id}`;
- copies catalog fields and **reads back `team`** — the ownership attribution
  Atlas stamped at create time (`spec/06`), trusted with a cheap existence/active
  check (orphans → `Unassigned`); owner-email mapping survives only as a fallback
  for VMs created out-of-band;
- sets `last_synced = now`.

VMs present last pull but absent now are **tombstoned** (`archived = 1`), never
hard-deleted. Sync errors are recorded on `Cluster.last_sync_error`; that
cluster's rows simply go stale — they are not removed.

> **Cadence:** every ~1–2 minutes. A newly-created VM appears within that
> window — "fresh enough" for a global *identity* index (it's an inventory, not
> a live console). A full `get_list` per cluster is trivial at POC/early scale;
> we do **not** add incremental sync until row counts actually hurt (below).

### Power state — lazy read-through (W4)

The list renders from registry rows (fast, always available). Live status is
fetched **after** paint, per visible row, cached briefly — this is what makes
the UI feel alive:

```
SPA → Central: GET /api/method/central.api.get_vm_status?vm={name}
Central:       Redis GET central:vm_status:{name}  → hit? return {cached:true}
Central → Atlas: get_value(Virtual Machine, name, "status")           # miss
Central:       Redis SETEX ~45s; persist status_cached/synced_at; return
```

A dead cluster yields `{unavailable:true}` for *its* rows only (not cached, so
the badge recovers automatically) — it never blocks the page or other regions.

### Browser updates — just refetch

The SPA keeps the list current by **refetching** (on the W4 status responses and
a light interval / on navigation) via frappe-ui's `useList`. No websocket
plumbing — normal refetch is enough for an identity list that changes on the
order of minutes.

## Caching layers

| Layer | Holds | Lifetime | Invalidated by |
|---|---|---|---|
| **Central registry rows** (MariaDB) | identity + last-seen status | durable | the periodic pull |
| **Redis** `central:vm_status:*` | live power state | ~45 s | TTL; status read-through |
| **Browser** (`useList`) | the rendered list | session | refetch |

The registry rows are the *durable* cache; the rest is faster, lossy, and always
rebuildable from them.

## Consistency model

- **Identity:** eventually consistent, bound = the pull interval (~1–2 min). The
  UI shows `last_synced` and a per-cluster staleness tag when a pull errored
  (`spec/05`), so lag is honest, never hidden.
- **Power state:** read-through, ≤ cache TTL stale by construction.
- **Never blocks:** no page render waits on a synchronous fan-out to clusters. A
  region down degrades *its* rows to stale identity + "unavailable" status; the
  dashboard always paints.

## Future — add only when scale demands it

These are deliberately **not** in v1. Each is an optimization with a clear
trigger; until the trigger fires, the two mechanisms above are correct and
simpler.

- **Incremental pull (watermark).** When per-cluster row counts make a full pull
  expensive, add a `Cluster.sync_watermark` and filter `modified > watermark`,
  with a periodic full reconcile to catch deletes. *Trigger: full pulls get slow.*
- **Event push (Atlas → Central).** When sub-second identity propagation is
  actually needed, Atlas adds `doc_events` on `Virtual Machine` that POST signed
  (HMAC, per-cluster secret, timestamped, idempotency-keyed) events to a Central
  ingest endpoint, which calls the **same `upsert_vm`**. Pull stays underneath as
  the reconciler — push never replaces it. *Trigger: "appears instantly" becomes
  a requirement.*
- **Websocket fan-out to browsers.** When refetch feels laggy at scale, publish
  registry changes to team-scoped socket.io rooms and patch the list in place.
  *Trigger: refetch is too coarse.*

## API surface

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET central.api.get_vm_status?vm=` | user session | W4 read-through (cached) |
| `POST central.api.sync_cluster?cluster=` | operator | on-demand full pull |
