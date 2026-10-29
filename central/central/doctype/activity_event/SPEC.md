# Activity Event

## Purpose

Activity Event is the customer-visible ledger for a team and its servers. A row records one event that already happened. Only the system writes rows. Customers read them through the activity API and the server Activity tab.

## Recorded events

The ledger records these sources:

| Source | Events |
|---|---|
| Server | Created, renamed, configured, powered, resized, terminated |
| Resource Action | The terminal state of each server action |
| VM Snapshot | Taken, kept, failed, deleted |
| Site and Site Domain | Site created, claimed and deleted, domain added and removed |
| Team | Created, renamed, archived, restored, suspended, ownership transferred |
| Team Member | Added, removed, roles changed |
| Team Invitation | Sent, resent, accepted, declined, revoked, expired |
| Team Role | Created, updated, deleted |
| Team SSH Key | Added, updated, deleted |

A server event also appears in the team feed. The team feed is API only.

## Visibility

`ActivityEvent.record` derives the team, server and required capability from the resource. A caller cannot widen who sees a row.

A reader sees a row in one of two ways:

1. The reader holds the row's required capability for the team.
2. The row names a server, and the reader holds that capability on that server.

A team feed also requires active team membership. A System Manager bypasses both rules. The query condition and the single-document permission check enforce the same rules.

## Request IP

The request address sits in `Activity Event IP`, not in the customer-readable table. The activity API returns the address only when the reader holds `team:manage_members` for the team. A direct DocType read is limited to a System Manager.

## Retention

Frappe Log Settings clears rows from `Activity Event` after 30 days by default. An operator changes the days in Desk. The same job removes the matching address rows.

## API and interface

`central.api.activity.server_activity` returns one server's events, including its sites and domains. `central.api.activity.team_activity` returns the team feed. Both page newest first with an opaque cursor.

The server page shows the Activity tab. The tab filters by category and expands one row for its full details and error.

## Backfill and failure

`backfill_activity_events` records the last 30 days of server history on migrate. A record key makes each write idempotent.

A failed write is logged and does not roll back the operation it describes. An unknown event name is a programming error and raises.
