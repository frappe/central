# Host Access Grant

## Purpose

A Host Access Grant gives one person SSH access to one host, or to every host, of a region for a fixed time. Warpgate in the region enforces the access. Submit grants the access, and cancel revokes it.

```text
Operator ── Desk ── Host Access Grant ── AtlasClient.for_operator ── Atlas /api/atlas/hosts ── Warpgate role grant
Person ── ssh -p 2223 <email>:<host>@warpgate.<proxy domain> ── Warpgate ── Central OpenID Connect sign-in
```

## Configuration

| Item | Value |
|---|---|
| Who creates grants | System Manager. The Atlas operator client requires the operator bypass. |
| Who can receive a grant | A user with the `Atlas Host Access` role. Central OpenID Connect refuses other users at Warpgate sign-in. |
| Warpgate admin | A user with the `Atlas Warpgate Admin` role opens the Warpgate admin UI. |
| Durations | 1, 3, 6, 12, or 24 hours. Atlas refuses an end time more than 24 hours away by default. |
| SSH address | `warpgate.<Region proxy domain>`, port 2223. |

Both roles are fixtures. Add both roles to the Allowed Roles of the Warpgate OAuth Client. See [OpenID Connect provider](../../../../spec/SSO.md#openid-connect-provider).

## Operation

1. Create a Host Access Grant. Choose the region first. The host field loads the region hosts from Atlas when it gets focus.
2. Choose one host or all hosts, the user, the duration, and a reason.
3. Submit. Central sets `expires_at` and asks Atlas to grant the access until that time. If Atlas refuses, the grant stays a draft. Submit again after you correct the cause.
4. Select **Show SSH Command** and run the command. Warpgate prints a link. Open it, sign in with Central, and approve the login.
5. Cancel the grant to end the access before `expires_at`. Revoking twice is safe.

One active grant opens a host to a person, so a cancel always ends that access. An all-hosts grant overlaps every host of the region. Cancel a grant and amend it to change the duration or the scope. The list shows Active, Expired, or Revoked from the document state and `expires_at`. No scheduled job runs.

## Validation

`central.tests.test_host_access_grant` checks the role check, the host requirement, grant on submit with the stored end time, all hosts, revoke on cancel, overlapping grants, the lock on the person, an Atlas refusal, and the SSH command.
