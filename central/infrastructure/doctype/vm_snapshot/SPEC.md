# VM Snapshots

## Purpose

A `VM Snapshot` is a copy of one server's disk, kept in the server's region. A customer can create a new server from it. Central takes, bills, and deletes each snapshot. Atlas only runs each command, and it keeps the image.

## Pricing rule

This is a product decision.

- Each server gets **2 free snapshots**. These are its 2 newest snapshots, whatever their type.
- Every older snapshot of that server costs money: its size in GB × the Snapshot rate, per month.
- A snapshot moves between free and paid by itself. When a newer snapshot is ready, the third-newest starts to cost money. When a snapshot is deleted, an older one can become free again.
- This stays true after the server is terminated. Its 2 newest snapshots stay free for as long as they are kept.
- The final snapshot taken before a terminate counts as one of the 2.

Example, with the rate at ₹6.50 per GB per month:

| Snapshot of server "shop" | Age | Cost |
|---|---|---|
| Daily | 1 day | Free |
| Daily | 2 days | Free |
| Manual, 20 GB | 5 days | 20 × ₹6.50 = ₹130 per month |

The operator changes these values without a code change:

| Setting | Location | Default |
|---|---|---|
| Price per GB per month | `Catalog Rate` for the `Snapshot` Resource Type, per currency, optionally per region | INR 6.50, USD 0.08 |
| Free snapshots per server | `Billing Settings.free_snapshots_per_server` | 2 |
| Hours a daily snapshot is kept | `Billing Settings.daily_snapshot_retention_hours` | 48 |

If a region has no Snapshot rate, Central cannot bill a snapshot there. It writes the reason on the snapshot and tries again the next time that server's snapshots change. The console shows "Price not set" for it.

## Snapshot types

| Type | Who starts it | Deleted on its own |
|---|---|---|
| Daily (`Automatic`) | Central, once a day, for each running server | Yes, after the retention hours, unless the customer keeps it |
| Manual | The customer | No |
| Final (`Terminate`) | A terminate with **Take a final snapshot first** | No |

Daily snapshots run only in a region with `Region.automatic_snapshots` on. It is off by default, until the region's hosts and storage can carry the load. A customer can turn daily snapshots off for one server (`Virtual Machine.skip_automatic_snapshot`).

**Keep** stops the deletion of one daily snapshot. It does not change the pricing rule: the snapshot is free while it is one of the 2 newest, and costs money after that.

## Operation

On the Snapshots page, a member with `server:snapshot` selects a Running, Stopped, or Paused server, reviews the price, and starts a manual snapshot. The same price dialog is available from a server's menu.

```text
insert --> after_insert job --> send_to_region() --> Atlas image (tagged with the snapshot name)
sync_pending_snapshots (every 5 minutes) --> sync() --> Available + size | Failed + reason
status becomes Available or Deleted --> apply_free_allowance(server) --> each snapshot free or billed
take_automatic_snapshots (daily maintenance) --> one Automatic snapshot per running server
delete_expired_snapshots (hourly maintenance) --> delete_from_region() --> Deleted
```

- Atlas sends no event for a snapshot, so Central reads each Pending one until it settles.
- A lost reply to the create call is found again by the image tag `central_snapshot`.
- A snapshot the region never recorded is marked Failed after 30 minutes.
- A failed snapshot keeps a safe reason on the record, links the full diagnostic through Error Log, and queues one notification after commit.
- One snapshot runs per server at a time.
- A deleted snapshot keeps its record, so its invoice lines still resolve.
- A paid snapshot is a `Subscription` with `vm_snapshot` set. Invoicing bills it in the snapshot's region.

## Terminate with a snapshot

The terminate `Resource Action` has `take_snapshot` set. Central stops the server, takes a `Terminate` snapshot, and destroys the server only after the snapshot is Available. If the snapshot fails, the terminate fails with `SNAPSHOT_FAILED` and the server stays stopped.

## Restore

The New Server page offers **Snapshot** as the source. A restore creates a new server in the snapshot's region, of the same kind as the source server. The disk must be at least the snapshot's size.

A snapshot of a Pilot server cannot be restored yet. A restored Pilot disk keeps the old server's identity, because Pilot applies its first-boot setup only once. `is_restorable` is off for these snapshots until Pilot can reset its identity.

## Permissions

A team member with `server:view` can read the team's snapshots. Taking, keeping, deleting, and restoring need `server:snapshot`. A terminate with a snapshot needs both `server:terminate` and `server:snapshot`. Only a System Manager changes a record in Desk.
