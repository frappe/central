# Central IAM

## Architecture

```mermaid
flowchart LR
    U[User] --> C[Central]
    C -->|server:* decision| D[Dispatch]
    D -->|signed token, X-Tenant-ID| A1[Atlas region A]
    D -->|signed token, X-Tenant-ID| A2[Atlas region B]
    A1 -->|Tenant boundary only| R1[Region A resources]
    A2 -->|Tenant boundary only| R2[Region B resources]
```

- Central is the global authority for users, Teams, roles, and capabilities. Every `server:*` decision is made here, before any regional call.
- A region never sees a capability. Central signs a short-lived, tenant-scoped token for the call it is about to make; the region checks only that the token's tenant matches the resource's tenant. See [Atlas coordination](ATLAS_COORDINATION.md).
- `System Manager` is the only authorization bypass.

## Permission Model

```mermaid
flowchart LR
    T[Team] --> M[Team Member]
    U[User] --> M
    M --> R[Team Role]
    R --> RC[Role Capability]
    RC --> C[Capability]
```

Central owns:

- `Team`
- `Team Member`
- `Team Role`
- `Role Capability`
- `Capability`
- `Team Invitation`
- `IAM Permission Probe`

A member receives capabilities through one path:

`Team Member -> Team Role -> Role Capability -> Capability`

There are no per-user capability overrides. A Team owner is an active
`Team Member` with the `Owner` role.

| Role | Intended access |
| --- | --- |
| Owner | All Team capabilities |
| Admin | Day-to-day team, server, and billing operations, excluding team deletion and ownership transfer |
| Developer | Full server operations |
| Viewer | Read-only server access |
| Billing | Billing and read-only server access |

A member can hold several role grants in a Team. Each grant is team-wide or scoped to one server or site. Create a custom Team role when a member needs a combination such as administration and billing.

Server is the atomic unit (capability model v3): role capabilities live at the
team and server level only. Server capabilities are `server:view`,
`server:create`, `server:power`, `server:resize`, `server:snapshot`,
`server:terminate`, `server:ssh-key`, plus `cluster:view` for placement. `server:view` also permits
opening a server or site. The
site-level (bench-plane) capabilities are deferred; see
[`CAPABILITIES.md`](../CAPABILITIES.md) for the full taxonomy.

## Resource Scope

A role grant applies to all resources (`resource_type = "*"`) or to one resource. A grant on a server applies to that server. A grant on a site applies to the server that the site runs on, because each site is one machine.

| Question | What counts |
| --- | --- |
| A team-wide action, such as create a server, manage storage, see billing, or manage members | Team-wide grants only |
| One server, such as power, resize, snapshot, terminate, or open | A team-wide grant, or a grant scoped to that server |
| A list, such as the fleet, snapshots, or notifications | A grant anywhere in the team, then only the rows of the allowed servers |

- Only `server:view`, `server:power`, `server:resize`, `server:snapshot`, and `server:terminate` can be scoped. A scoped grant drops every other capability of its role.
- A scoped grant must name a server or site of the same Team. The Owner role is always team-wide. A grant whose resource no longer belongs to the Team grants nothing.
- `iam.can(user, team, capability, server=None)` answers the first two questions. Without `server`, it is the team-wide question. Routes that act on one server pass it. `iam.can_on_any_server` answers the list question.
- The permission rules for Virtual Machine, Site, VM Snapshot, Resource Action, and Site Domain filter lists by the allowed servers and check the server on each record.
- Pricing a resize reads the plans and the current configuration of one server. Those two billing reads accept `server:resize` on that server in place of `billing:view`.
- A notification that is about a server records it in `Team Notification.server`. A scoped member sees and receives only the notifications for its servers.
- The console reads each server's capabilities from the `capabilities` field on its row, so it shows only the actions that the member can do on that server.

## User And Invitation Flow

```mermaid
flowchart TD
    U[User created] --> R[Assign Central User role]
    R --> PT[Create personal Team]
    PT --> OM[Add active Owner membership]
    OM --> P{Pending invitations?}
    P -->|No| D[Done]
    P -->|Yes| A[Accept matching invitations]
    A --> IM[Add invited Team memberships]
```

- Every non-guest user receives a personal Team.
- Team creation always creates an active Owner membership.
- Existing users must explicitly accept invitations.
- For a newly created user, invitations sent to the same email are accepted
  after the personal Team has been created.
- Invitations cannot grant the `Owner` role.
- Accepting an invitation adds or activates membership in the inviting Team; it
  does not replace the user's personal Team.

Example: John and Jane each have a personal Team. If John invites Jane to
John's Team, there are still two Teams. Jane owns Jane's Team and is also a
member of John's Team.

## Deferred Scope

- Resource groups
- Partner and reseller access
- Bench authorization
- Billing enforcement
- Delegated custom-role administration
