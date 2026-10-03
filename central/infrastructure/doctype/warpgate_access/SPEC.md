# Warpgate Access

## Purpose

A Warpgate Access gives one person time-limited access through Warpgate: SSH to one host, SSH to every host of a region, or the Warpgate admin UI. Submit grants the access. Cancel or expiry revokes it.

```text
Operator ── Desk ── Warpgate Access ── AtlasClient.for_operator ── Atlas /api/atlas ── Warpgate
Person ── ssh -p 2223 <email>:<host>@warpgate.<proxy domain> ── Warpgate ── Central OpenID Connect sign-in
```

## Configuration

| Item | Value |
|---|---|
| Who creates access | System Manager. The Atlas operator client requires the operator bypass. |
| Access types | One host, All hosts, Admin. |
| Host durations | 1, 3, 6, 12 hours, or 1 day. A host access needs the `Atlas Host Access` role. |
| Admin durations | 1, 6, 12 hours, 1, 7, or 30 days, or Never. Admin access adds the `Atlas Warpgate Admin` role, which opens the admin UI of every region. |
| SSH address | `warpgate.<Region proxy domain>`, port 2223. |

## Operation

1. Create a Warpgate Access. For host access, choose the region, then the host.
2. Submit. Host access asks Atlas to grant the host role until `expires_at`. Admin access adds the admin role.
3. Cancel to revoke. Host access calls the Atlas revoke route. Admin access removes the admin role and closes the person's sessions in every region.
4. Job `expire_access` runs every minute and revokes each active access whose `expires_at` passed. A failed revoke runs again on the next run.
5. A revoke closes every live Warpgate session of the person, HTTP and SSH.

One active access gives each permission to a person. Status is Active, Expired, or Revoked.

## Validation

`central.tests.test_warpgate_access` covers the role check, durations, grant and revoke for each type, overlap, the lock on the person, Never, and the expiry job.
