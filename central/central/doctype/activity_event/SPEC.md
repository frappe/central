# Activity Event

## Purpose

Activity Event is the customer-visible ledger for a team and its servers. A row records one event that already happened. Only the system writes rows. Customers read them through the activity API and the dashboard.

## How events are recorded

Frappe writes a Version for each save of a DocType that tracks changes. `record_version` runs on `Version.after_insert` and turns the tracked fields of that Version into events. Frappe owns the diff, so Central does not compare documents itself.

```text
save() ─► Frappe writes Version ─► record_version ─► Activity Event rows
insert / delete of a tracked DocType ─► record_created / record_deleted
Resource Action reaches a final state ─► ActivityEvent.record_action
Central returns a console URL ─► ActivityEvent.record
```

`tracked.py` lists each tracked DocType: its event prefix, category, required capability, the fields the feed shows, and the fields that are events of their own.

| DocType | Events |
|---|---|
| Virtual Machine | Renamed, configuration changed, SSH keys changed, SSH console opened, serial console (TTY) opened |
| Resource Action | Server created, started, stopped, restarted, resized, terminated |
| VM Snapshot | Requested, available, failed, deleted |
| Site and Site Domain | Created, claimed, deleted |
| Team | Created, settings changed, members changed, ownership transferred, suspended, archived, reactivated, opened by support |
| Team Role | Created, changed, deleted |
| Team Invitation | Sent, resent, accepted, declined, revoked, expired |
| Team SSH Key | Added, renamed, rotated, deleted |

One save can produce more than one event. Each event keeps only its own details, so a detail never shows under a weaker capability. For example, a server rename needs `server:view`, and a server SSH key change needs `server:ssh-key`.

A console event needs `server:console`. Central writes one event for each console URL it returns. A refused request or an Atlas failure returns no URL and writes no event. During support access the session user is the operator, so the event stores the operator as the actor. Customers see the operator as Frappe Cloud.

`db_set` writes no Version. A tracked field that changes through `db_set` calls `save_version()` after it, so the feed sees the change.

## Visibility

`ActivityEvent.record` takes the team and server from the resource. A caller cannot widen who sees a row. The DocType is for operators only, like Team Notification. The activity API applies `iam.get_capability_gate`:

1. A reader sees an event when they hold its required capability for the team.
2. A reader with a grant scoped to servers sees an event only when it names one of those servers.
3. A System Manager sees every event.

`team_activity` also requires active team membership. `server_activity` requires `server:view` on the server.

## Failure

The event row is written in the same transaction as the change it describes. A failure to write it fails the change, so the feed never misses an event without an error.

## Retention

Log Settings owns the retention. Its Activity Event row clears rows after 365 days by default, and an operator changes the days in Desk. The backfill patch reads the same value and fills that window from Versions, Deleted Document and Resource Action when the feed is first deployed. Versions stay, so Desk keeps the full history of each document.

## API and interface

`central.api.activity.server_activity` returns one server's events, including its sites, domains and snapshots. `central.api.activity.team_activity` returns the team feed. Both page newest first with an opaque cursor over `(creation, name)`. Both take an optional `category` and an optional `since` and `until` date range.

Each event has a `sentence`, such as `{actor} restarted {resource}`. The API translates it for the reader. The actor is the person behind the event. A guest session acts for the person the record names, such as the invitee who accepts. A job, a schedule or a region report has no actor, and its sentence says only what happened, such as `Settings on {resource} changed`. A failed server action reads `{actor} tried to restart {resource}`. A change to team members is one event per member: added, removed, joined, left, or access changed. The resource label is the resource title when the event is written, so a deleted resource keeps its name in the feed. An event without an actor carries `initiator` when its resource names the person who initiated it, such as `requested_by` on a VM Snapshot that the region reports ready. `initiator_field` in `tracked.py` names that field, and the API reads it with the page, so the row does not store it. An operator reads as Frappe Cloud to a customer and by name to another operator.
