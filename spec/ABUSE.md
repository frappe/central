# Abuse protection

## Purpose

This document is the Central part of abuse protection in Frappe Cloud v2. It covers abuse that starts from, or targets, tenant resources in an Atlas region, and the messages to customers and operators about it.

Status: planned. Central does not implement this design yet. The DocType layouts in [Abuse layouts](ABUSE_LAYOUTS.md) need engineer approval before implementation. Change this document before you change the design.

Central owns all policy: profiles, exceptions, signals, cases, the ladder, reports, messages, CERT-In, and public IP history. Watcher, a planned module of Cargo in each region, finds abuse and sends findings to Central. It owns the finding codes, thresholds, windows, feeds, and calibration. See [Cargo Watcher](https://github.com/frappe/cargo/blob/develop/docs/watcher.md). Atlas exports metrics and logs, and applies or lifts a restriction when Central calls it. See the [Atlas abuse documentation](https://github.com/frappe/atlas/blob/develop/docs/abuse/index.md). Cargo also owns the regional log bucket, its object layout, its keys, and the per-VM metric table in Datum. See [Cargo abuse logs](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md). CERT-In reporting is in [CERT-In](CERT_IN.md).

## Scope

In scope:

- Outbound abuse from VMs: floods, scans, brute force, spam, reflectors, C2, and crypto mining.
- Hosted content on proxy sites: phishing, malware, and illegal content.
- Inbound DDoS on tenants.
- Report intake, customer messages, operator alerts, and CERT-In reporting.

Out of scope:

- 180-day logs for all ICT systems (CERT-In direction (iv)), other than the logs in [Cargo abuse logs](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md).
- Guest spoofing and tenant-to-tenant mesh traffic. WG Mesh `local_vms` and `can_communicate` already stop them.
- A guest-side agent. Guests are untrusted.
- Signup data and identity validation (CERT-In direction (v)).
- Infrastructure VMs of tenant 0. Central does not know them, so it skips their findings.

## Principles

1. Watcher detects and Central decides. Atlas exports metrics and logs, and applies or lifts a restriction when Central calls it. Atlas does not know teams, trust tiers, thresholds, or contacts. Watcher does not know teams, trust tiers, profiles, or contacts.
2. Atlas never acts alone on abuse. Only an Atlas operator can apply an emergency restriction.
3. Restrictions live in a layer that the tenant API cannot write. Tenant firewall, route, and IPv4 changes cannot widen them.
4. Every restriction has a reason, an actor, a case, and an end condition. Terminate by an operator is the last step.
5. Restrict traffic, never compute. The abuse system never pauses or stops a VM.
6. Keep evidence before it is destroyed. Central snapshots the disk before it terminates a server with an open case or an active restriction. Never stop and start a VM to collect evidence.
7. Detection failure must not block customers. If Datum, Watcher, Atlas, or Central is down, nothing new is applied, and automatic restrictions still end at `expires_at`.
8. Atlas stays backward compatible: optional fields and new endpoints only. Watcher deploys last. See [Deploy order](#deploy-order).

## Who does what

| Component | Responsible for | Acts alone |
|---|---|---|
| Metal (each host) | `restrictions` and `is_port_25_blocked` in the VM network object, per-VM counters exported to Datum, NAT and SNI logs uploaded to the log bucket, the `metal_abuse` chain, the `smtp_outbound` port 25 block | No |
| Atlas app (each region) | The restriction API and the port 25 API, which read, merge, and replace the Metal VM network object. The log write keys from Cargo in host and proxy config. Atlas keeps no restriction record. | Emergency restrictions by an Atlas operator only |
| HTTP proxy | Static rate limits, the abuse tombstone, the access log upload | No |
| Cargo | Log bucket and keys, the per-VM metric table in Datum and the `watcher` read user | No |
| Watcher (Cargo) | Finding codes, threshold rules, windows, thresholds, feeds, mining detection, hostname and address checks, calibration, NAT log attribution, the `abuse` report to Central | No |
| Central | Profiles, exceptions, brand-term scoring, Abuse Signal, Abuse Case, the policy engine, reports, all customer messages, the abuse dashboard, CERT-In, public IP history | Yes |
| Pilot | Nothing | Not applicable |

```text
Metal host          metrics      Datum (Cargo)       read user     Watcher (Cargo)
counters      ───────────────▶  vm_abuse_*, 30 d  ─────────────▶  finding codes, thresholds
NAT, SNI logs ───────────────▶  Cargo log bucket  ─────────────▶  feeds ◀── blocklists, DNSBLs
                                       ▲            read key      NAT log attribution
HTTP proxy: limits, tombstone, ────────┘                                │ abuse report
            access log                                                  ▼
                                                                  Central: profiles, Abuse Signal
                                                                  Abuse Case, policy engine
                                                                  messages, Abuse Report, CERT-In
                                                                        │       ▲
metal_abuse  ◀── VM network object ───── Atlas app ◀── restriction and ─┘       │
restrictions,    read, merge, replace    port 25 API                            │
port 25 block                                     └───── GET VM, repair scan ───┘
```

## Roles and capabilities

| Name | Kind | Use |
|---|---|---|
| `Abuse Responder` | Desk role, planned. Not tied to a team. | Reads and writes Abuse Case, Abuse Report, Abuse Exception, Abuse Signal, Public IP Assignment, and Port 25 Request. Works the abuse dashboard. |
| `security:view` | Team capability, planned | Reads the team's abuse cases and gets Security email. Owner and Admin roles get it by default. |
| `security:manage` | Team capability, planned | Responds to a case, requests a lift or an exception, applies and lifts self-quarantine, and requests a port 25 unblock. Implies `security:view`. Owner, Admin, and Developer roles get it by default. These are the roles that have `server:network`. |

Add `security:view` and `security:manage` to [Capabilities](../CAPABILITIES.md) and the fixtures in the implementation change. Developer gets `security:view` through the implication. Customers read cases only through the dashboard API, filtered by `security:view`. Each customer action on a case, a restriction, an exception, or a port 25 request needs `security:manage`.

## Findings from Watcher

Watcher finds abuse. It is a planned module of Cargo in each region. It reads the per-VM metrics in Datum, the NAT, SNI, and proxy access logs in the log bucket, and external feeds and shared abuse databases. It sends each finding to Central in an `abuse` report. See [Reports from Cargo](#reports-from-cargo).

Cargo documents detection:

- Inputs, with the Atlas counters and logs: [Cargo inputs](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#inputs).
- Finding codes: [Cargo finding codes](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#finding-codes).
- Severity: Watcher takes the severity of a finding from the Abuse Threshold Trigger row that matched. So one finding code can have triggers of different severity. For example, the slow scan of `Recon:VM/Portscan` is Low. See [Cargo thresholds](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#thresholds).
- Rules, windows, and threshold values: [Cargo threshold rules](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#threshold-rules), [Cargo windows](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#windows), and [Cargo thresholds](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#thresholds).
- Feeds, hostname checks, and address checks: [Cargo feeds](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#feeds).
- Baseline, shadow, red team, and activation: [Cargo calibration](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#calibration).

Central acts on findings:

- Watcher knows no teams, trials, or profiles. Central maps the subject of each finding to a team, and applies the [profile](#profiles) and any approved [exception](#exceptions).
- `virtual_machine` is the Atlas VM ID, for example `vm-0a1b2c3d4e`. Central matches it to `Virtual Machine.atlas_vm_id`. Central skips a finding on a VM that it does not know. These are the tenant 0 infrastructure VMs.
- Central reads no metrics and no logs. Neither Central nor Watcher reads the content of VM traffic.
- Central makes one finding itself, `Phishing:Site/LookalikeDomain`, because it needs the team age. See [Phishing sites](#phishing-sites).
- A flood or a scan can continue for about 3 min before Central restricts the VM. No automatic limit exists before that. See [Cargo windows](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#windows).

The HTTP proxy has static limits for each client address and site: `limit_req` 100 requests a second with a burst of 500, and `limit_conn` 200. Central does not change them. See [Atlas HTTP proxy](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md#http-proxy).

### Profiles

Central picks a profile for each server when a finding arrives, from team data. The profile stays in Central. Watcher and Atlas do not get it.

| Profile | For | Multiplier |
|---|---|---|
| `strict` | Free trial servers, and teams that never paid | 0.5 |
| `standard` | All other servers | 1 |
| `relaxed` | Trust tier 3 (Advance) or higher, and no case in 90 days | 2 |

When rules overlap, Central uses the first match:

1. A free trial server is `strict`.
2. A team at trust tier 3 (Advance) or higher is `relaxed`. This includes teams without payments that have a manual override.
3. A team that never paid is `strict`.
4. All other servers are `standard`.

- Central acts on a finding when every value in `measured` reaches the matching value in `threshold` times the multiplier.
- `threshold` holds the standard values. Watcher reports a finding from 0.5 times `threshold`, the strict level, so each profile gets the findings that it needs.
- A finding below the level of the profile writes no Abuse Signal. A later update of the same `finding_id` can reach the level.
- `measured` and `threshold` hold only the volume triggers: rates, counts of addresses, and counts of attempts. These are the triggers that scale with the profile. See [Cargo thresholds](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#thresholds).
- Watcher checks ratio and shape conditions at their standard values, for example the answer ratio, the packet size, and bytes out against bytes in. It puts the measured ratios in `evidence`. The multiplier does not change them.
- A feed match or a stratum match has empty `measured` and `threshold`. Central acts on it for every profile.
- The multipliers are constants in code, not settings. The strict multiplier must equal the Watcher report level, so the two change together.
- There is no profile for infrastructure VMs.

### Exceptions

An approved [Abuse Exception](#abuse-exception) changes one finding code on one server until it expires. It sets another multiplier, or disables the finding code for the server. Central reads it when a finding arrives. Watcher and Atlas get nothing.

### Signals

An Abuse Signal is one finding on one server, bucket, or site. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-signal).

- Fields: team, server, bucket, hostname, address, finding code, severity, source, `finding_id`, `window_start`, `window_end`, `measured`, `threshold`, evidence, `is_shadow`, `is_trusted_source`, and `is_false_positive`.
- Central matches a finding to a signal by `finding_id`. A known `finding_id` updates the signal and moves its `window_end`. A new `finding_id` adds a signal.
- Evidence holds the port class, ports, the protocol, counts, ratios, destination prefixes truncated to /24 or /48, the feed that matched, and the feed entry that matched. See [Reports from Cargo](#reports-from-cargo). It holds no payloads and never names a reporter.
- A finding with `is_shadow` writes a signal with `is_shadow`. Central stores it, takes no action, and opens no case.
- Every other signal goes to the policy engine. The policy engine finds or opens the case for (team, server, finding code), or for (team, bucket, finding code), and links the signal.
- Sources: Watcher, Brand Scoring, Report, or Operator.

## Abuse Case

An Abuse Case is the record of one abuse problem on one server. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-case).

- Central keeps one open case for each (team, server, finding code), or for each (team, bucket, finding code).
- The name is `AC-.#####`. It is the reference in mail subjects, for example `[AC-00192]`.
- A case links its Abuse Signals. They come from Watcher findings, brand-term scoring, Abuse Reports, or an operator.
- A case for a public bucket names the bucket instead of a server. See [Public buckets](#public-buckets).
- Status, ladder level, deadlines, and restrictions change only through the policy engine or an operator action. Nobody edits them on the form.
- Severity is Low, Medium, High, or Critical. Three signals of one finding code on the case in 24 h raise it to High.

### Lifecycle

```text
Open ◀─────────────────────── new signal, same ladder level ─────────────────────────────┐
 │ │                                                                                     │
 │ └── no notice possible ───▶ Notification Failed                                       │
 │                               │ marked delivered by another channel                   │
 │                               ▼                                                       │
 └─────── notice sent ───────▶ Awaiting Customer ── fixed before the deadline ────┐      │
                                 │           │                                    │      │
                        deadline │           │ needs an operator                  │      │
                                 ▼           ▼                                    │      │
                            Restricted ◀─▶ Escalated                              │      │
                                 │           │                                    │      │
                   fixed, lifted │           │ operator decision                  │      │
                                 ▼           │                                    │      │
                               Resolved ◀────┴────────────────────────────────────┘      │
                                 │ │                                                     │
                                 │ └─────────────────────────────────────────────────────┘
                                 │ 7 days without a new signal: Fixed
                                 ▼
                               Closed ◀── an operator, from any status: False Positive,
                                          No Response, Terminated, Suspended, or Duplicate
```

| Status | Meaning | Next status |
|---|---|---|
| Open | The case exists. No customer notice is sent yet. | Awaiting Customer when a notice is sent. Notification Failed when no notice is possible. |
| Awaiting Customer | A notice is sent. The deadline runs, if the step has one. | Resolved when the customer fixes the cause before the deadline. Restricted at the deadline. Escalated when the case needs an operator. |
| Notification Failed | No customer notice could be sent. The deadline does not start. Automatic restrictions still apply. | Awaiting Customer when a responder marks the notice as delivered by another channel. |
| Restricted | A restriction from the ladder is active. | Resolved when the cause is fixed and the restriction is lifted. Escalated when the case needs an operator. |
| Escalated | The case waits for an operator decision: a dispute, a deadline reached on a paid team, an isolate, a `Failed` restriction, or illegal content. | Restricted or Resolved, from the operator decision. |
| Resolved | The cause is fixed and no case restriction is active. | Closed with resolution Fixed after 7 days without a new signal. Open at the same ladder level on a new signal. |
| Closed | The resolution is set. Central sends the close reply to reporters. | None |

- The 7-day window is the same as the window for automatic return. See [Lifts](#lifts).
- Only Central sets the resolution Fixed, when a Resolved case closes itself.
- An operator can close a case from any status. The resolution must be False Positive, No Response, Terminated, Suspended, or Duplicate.
- A closed case never opens again. A new signal after close opens a new case. The closed case still counts as history for repeats.
- A case is open in every status other than Closed.

Resolution values: Fixed, False Positive, No Response, Terminated, Suspended, Duplicate.

## Ladder

| Level | Action | Applied by | Ends |
|---|---|---|---|
| 0 | Signal | Watcher finding, or Central | Not applicable |
| 1 | Notice | Central | Not applicable |
| 2 | `port_block` or `egress_throttle` | Central or an operator | Lift or `expires_at` |
| 3 | `quarantine` | Central or an operator | Lift |
| 4 | `isolate` | Central (trials, confirmed mining) or an operator | Operator only |

- What each restriction kind blocks is in [Atlas restriction kinds](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md#restriction-kinds).
- The ladder stops at isolate. There is no pause and no stop.
- History counts per team over 90 days. A new VM does not reset it.
- When a VM is isolated, Central also tombstones its sites.
- Restrictions add up. Lifting one never lifts another.
- The abuse dashboard lists level 2 to 4 restrictions older than 14 days for review.

Outside the ladder, operators keep `Team.suspend` (fraud, legal hold) and terminate. No policy applies them. Today `Team.suspend` skips `Paused` servers (`central/identity/doctype/team/lifecycle.py`). Fix this before abuse cases depend on it.

### Tracks

The ladder is one track. Three tracks are outside it:

| Track | Applies to | Rule |
|---|---|---|
| Sites | Phishing and illegal content | Central tombstones the site on the proxy. This equals level 3. Only an operator lifts it. |
| Protection | Inbound DDoS on the customer | `ingress_throttle` and the operator steps protect the victim. The dashboard shows them as protection. They never count as history. |
| Port 25 | The `smtp_outbound` port 25 block from `is_port_25_blocked`. See [Email](#email). | Not a ladder step and not history |

### Lifts

Each customer action below needs `security:manage`.

- Self-lift: once for each case, for level 2 or 3, after the customer writes what they fixed.
- Automatic return: the same finding category on the team within 7 days of a self-lift puts the restriction back, with no new deadline. After that, only an operator lifts it.
- Lift request: for any other restriction, the customer asks on the case page. The response kind is `Lift Requested`. A responder decides.
- Self-quarantine: the customer can apply `quarantine` from the Security tab. See [Self-quarantine](#self-quarantine).

### New servers

While a team has an open case at level 3 or 4, every new server starts with the same restriction. Central sends it in the optional `restrictions` field of the Atlas VM create request. Atlas puts it in the Metal network object. Each inherited restriction has its own `idempotency_key`, the name of a new Resource Action, and the `case_reference` of the case. The restriction ends with the case.

- Restrictions and `is_port_25_blocked` are part of the create fingerprint, so a retried create with the same key sends the same values.
- Atlas accepts these two create fields only from a Central identity. It refuses them from any other caller with HTTP 403.
- Restrictions are in the Metal VM network object, so they move with a VM on migration.

### Restrictions

Central applies and lifts restrictions through the Atlas restriction API. See [Apply a restriction](#apply-a-restriction).

- Kinds: `egress_throttle`, `ingress_throttle`, `port_block`, `quarantine`, and `isolate`.
- `port_block` takes explicit ports with their protocol. Central resolves port classes to ports from its copy of the [Atlas port classes](https://github.com/frappe/atlas/blob/develop/docs/abuse/metrics.md#port-classes). Atlas does not know port classes.
- Atlas keeps no restriction record. Each restriction is an entry in the `restrictions` list of the Metal VM network object. Metal renders the active entries in the `metal_abuse` chain. See [Atlas restriction kinds](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md#restriction-kinds).
- The entry ID is the `idempotency_key`, the name of the Resource Action. Central extends and lifts the restriction by this ID.
- Central keeps one Abuse Case Restriction row for each entry. See [Restriction states](#restriction-states).

Who changes restrictions:

- Normal: the policy engine or an operator in Central calls the restriction API. Central records a Resource Action with action `restrict` (a new action) and a system actor, and links the case.
- Emergency: an Atlas operator applies a restriction with a Desk action on the Atlas Virtual Machine. The entry ID is `atlas-` and a random suffix. Atlas adds a Comment on the VM with the user, the kind, and the reason. Central finds the entry in its repair scan, adds a row with `applied_by` Atlas operator, and posts it to Raven `#abuse`. Central links the row to an open case of the server, or opens a case.
- Expiry: Central knows the end from its own `expires_at`. Metal skips an entry after its `expires_at`, and Atlas removes the entry on its next change of the VM network. Atlas sends nothing at expiry.

### Restriction states

Each Abuse Case Restriction row has one of these states. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-case).

| State | Meaning | How Central learns it |
|---|---|---|
| `Pending` | Central sent the call. It does not know the response yet. | Central sets it before it sends the call. |
| `Saved` | Atlas returned the entry in the desired network of the VM. Metal has not applied it yet. | The response of the call. The repair scan, after a lost response. |
| `Applied` | Metal applied the network that holds the entry: `observed_generation` reached the `desired_generation` of the response. | The repair scan. The response, when `observed_generation` already reached `desired_generation`. |
| `Failed` | Atlas refused the call with `409 host_unsupported` or a validation error, or Metal reported `host_error`. | The response, or the repair scan |
| `Lifted` | The entry was removed before its `expires_at`. | The response of the lift call. The repair scan, for an entry that an Atlas operator removed. |
| `Expired` | The `expires_at` of the row passed. | Central's own `expires_at`. Central asks Atlas nothing. |

The repair scan reads the Atlas `GET` VM response: `restrictions`, `is_port_25_blocked`, `desired_generation`, `observed_generation`, and `host_error`. It runs every minute for each VM with a `Saved` row. For all other VMs, it runs in the normal repair scan, `central.integrations.servers.reconcile`. For each VM, the scan does these steps:

1. A `Saved` row becomes `Applied` when `observed_generation` reached its `desired_generation`.
2. A `Saved` row becomes `Failed` when `host_error` is set.
3. A `Pending` row becomes `Saved` when its ID is in `restrictions`. This occurs after a lost response. The Resource Action stops being uncertain. If the ID is not in `restrictions`, the row stays `Pending`, and the Resource Action stays uncertain for an operator. Central does not send a second apply.
4. A `Saved` or `Applied` row whose ID is not in `restrictions` before its `expires_at` becomes `Lifted`, unless Central lifted it. This is an Atlas operator lift.
5. An entry with an `atlas-` ID that Central does not know is an emergency restriction. See [Restrictions](#restrictions).

Other errors may be transient: the `409` conflict when the network lock is busy, a timeout, or a `5xx`. The row stays `Pending`, and Central retries with the same `idempotency_key`. Central tells the two `409` errors apart by `error.code`.

A successful extend with `PATCH` stores the new `desired_generation` and sets the row back to `Saved`. The repair scan sets `Applied` again.

On VM create, the Atlas response has `restrictions` and `is_port_25_blocked`. When both are missing, the host runs an old Metal and the VM has no port 25 block and no inherited restriction. Central sets the inherited rows to `Failed`, posts to Raven `#abuse`, and sets the port 25 block through the port 25 route after the host update.

Central sets `ended_by` on the row. Atlas does not send it.

- `Central`: Central lifted the restriction. The Resource Action of the lift names the customer or the operator.
- `Expiry`: the `expires_at` of the row passed.
- `Atlas operator`: the entry left the network before its `expires_at`, and Central did not lift it.

On `Failed`, Central sets the case to Escalated and posts to Raven `#abuse`. Central does not apply the restriction again with a new key. An Atlas that runs on a Metal host without restriction support answers `409 host_unsupported` and saves nothing. Central sets the row to `Failed` in the same way.

## Policy engine

`central/abuse/policy.py` picks the next step. Its inputs are the finding, the severity, the Trust Tier Level, the account age, the paid history, and earlier cases.

Default escalation:

| Finding | Escalation |
|---|---|
| Outbound flood, SYN flood | `egress_throttle` at once, and a notice. A repeat in 7 days: quarantine. |
| Scan, brute force | `port_block` on the matched port class at once. Notice, 24 h deadline. Exception: a trial or a team that never paid gets `isolate` at once. |
| `Smtp:VM/BlockedPort25` | Helpful notice: use port 587 or 465 |
| `Spam:VM/Smtp` | Notice. A DNSBL listing: see [DNSBL response](#dnsbl-response). |
| Reflector | `egress_throttle` at once, and a notice with a fix guide |
| Mining | See [Mining](#mining). |
| C2 | Notice: likely compromise |
| Lookalike domain | An operator reviews it. No automatic step. |
| Phishing site | See [Phishing sites](#phishing-sites). |
| Illegal content | A responder through `#abuse-p1`. Tombstone or isolate. Set `is_legal_hold` on the case. |
| Inbound flood | `ingress_throttle` and a protection notice. See [Inbound DDoS](#inbound-ddos). |

- An immediate level 2 restriction from a finding has `expires_at` 24 h after it is applied. So a failure in Watcher or in Central never leaves it in place for long.
- While the match continues, Watcher updates the finding with a later `window_end`, and the signal moves its `window_end`. When less than 12 h of the restriction remain, Central extends it with a new `expires_at`. See [Calls to Atlas](#calls-to-atlas).
- An extension never resets the deadline or the ladder level.
- Example: a scan from a trial that never paid is isolated. The same scan from a Tier 3 team that paid for 12 months gets a `port_block`, a notice, and 24 h.
- At a deadline, the policy engine takes the next ladder step and sends `abuse_restriction_applied`.
- Abuse history lowers the trust tier. A resolved case with a fix restores the tier after 90 days.

The finding codes and their meaning are in [Cargo finding codes](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#finding-codes).

## Abuse Exception

An Abuse Exception lets a team change how Central acts on one finding code on one server for a fixed period. Example: an authorized penetration test. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-exception).

- A member with `security:manage` requests it on the server's Security tab. A responder approves or rejects it.
- Fields: team, server, finding code, effect (a multiplier, or disabled), reason, expiry, and approver.
- The expiry is at most 90 days after the start.
- Central applies an approved exception to findings until it expires or a responder revokes it. The exception stays in Central. Watcher and Atlas get nothing.
- The controller refuses a multiplier below 0.5. Watcher reports nothing below the strict level, so a lower multiplier has no effect.
- The controller refuses the `smtp_outbound` port 25 block. Port 25 has its own flow. See [Email](#email).

## Controls

Neither Central nor Watcher reads the content of a VM's traffic. Metal reads only the TLS server name and, for mining, the first payload bytes of new flows to non-standard ports. The AUP and the privacy policy must say so before Metal turns on the SNI log.

### Email

Port 25 is blocked only when Central asks. `is_port_25_blocked` is a field of the Metal VM network object. A missing field means open. For a VM with `is_port_25_blocked` set, the `smtp_outbound` block in Metal drops new TCP flows to port 25. The submission ports 465 and 587 stay open. See [Atlas metal_abuse chain](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md#metal_abuse-chain).

- Central sets `is_port_25_blocked: true` in every VM create request.
- Central changes it on an existing VM through `PUT /api/atlas/virtual-machines/<id>/port-25` with `is_blocked`. See [Atlas port 25 API](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#port-25-api).
- VMs created before the rollout keep port 25 open. Central sets the block on such a VM on a DNSBL finding or a spam finding. A responder can also set it from the case view. See [DNSBL response](#dnsbl-response).

A Port 25 Request holds one unblock request for one server. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#port-25-request).

- Status: Pending, Accepted, Rejected, or Revoked.
- A server has at most one open request. An open request is Pending or Accepted.
- Accepted clears `is_port_25_blocked` on the VM through the Atlas port 25 route. Revoked sets it again through the same route.
- `decided_by`, `decided_at`, and `abuse_case` are read only. Central sets them.

Port 25 unblock flow:

1. A member with `security:manage` creates a Port 25 Request on the server's Security tab: purpose, sending domain, reverse DNS name, and bulk-mail policy. The status is Pending.
2. Central accepts the request automatically for trust tier 3 and higher when the team has no open case. Otherwise the request goes to `#abuse`, and a responder accepts or rejects it with a decision reason.
3. Only a server with a dedicated public IPv4 can get an unblock. Shared NAT addresses are never unblocked.
4. On acceptance, Central sets the status to Accepted and sends `is_blocked: false` for that VM to the Atlas port 25 route.
5. The customer sets reverse DNS on the address.
6. Central sends `smtp_unblock_decided` with the result.
7. A responder can revoke an Accepted request. A DNSBL listing or a spam trap hit revokes it automatically. See [DNSBL response](#dnsbl-response).

### DNSBL response

- A DNSBL listing, or an SNDS spam trap hit, on an address with port 25 open opens a case. Central sets the Port 25 Request of the server to Revoked, sets its `abuse_case` to the new case, and sends `is_blocked: true` to the Atlas port 25 route.
- A VM created before the rollout has port 25 open and no Port 25 Request. On a DNSBL finding or a spam finding on it, Central sends `is_blocked: true` to the Atlas port 25 route. The customer can then create a Port 25 Request.
- For `Spam:VM/Smtp` with a DNSBL listing, Central applies `port_block` on the ports of the `smtp` and `submission` classes. An operator gets the address delisted.
- DNSBL notices that arrive by email become Abuse Reports. See [Report intake](#report-intake).
- Every hour, Watcher checks two sets of addresses against DNSBLs, Microsoft SNDS, and Shadowserver: the dedicated public IPv4 and IPv6 addresses of each VM, and the public source addresses in the NAT log. Watcher reports each listing as a finding. See [Cargo feeds](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#feeds).
- A finding on a dedicated address has `address` and `virtual_machine`. It follows the normal policy: a case, the response above, and the revoke of the Port 25 Request.
- Central checks through [Public IP history](#public-ip-history) when the server got the address. If the server got it less than 7 days before Central gets the finding, Central posts the listing to Raven `#abuse` and opens no case for the new team. An operator gets the address delisted.
- A finding on a shared NAT address has `address` only. It names no single server. Central posts its listing to Raven `#abuse` and opens no case.

### Phishing sites

- Central suspends a site with `proxy.suspend_site(name, reason_code)` in `central/integrations/proxy.py`. The proxy serves a branded suspended page with HTTP 403 for abuse, or HTTP 451 for a legal hold, and a link to the abuse page.
- Central suspends automatically only when the finding has `is_trusted_source`, the reporter is Trusted, or another signal corroborates it. Otherwise an operator checks first.
- Only an operator lifts a site suspension.
- Watcher checks the hostnames in the proxy access logs against phishing feeds, and reports a match with `Phishing:Site/Reported`. Central finds the site through Site Domain, then proxy routes. See [Cargo feeds](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#feeds).
- Central writes an Error Log for a hostname that it cannot find. It opens no case for it.
- Central gives a score to the hostname of each new Site Domain on a team younger than 30 days. A hostname with a brand term is an Abuse Signal with `Phishing:Site/LookalikeDomain`, Low severity, and source Brand Scoring, for an operator to review. Central does this, not Watcher, because it needs the team age.

### Public buckets

This flow applies only after Cargo offers public buckets. Cargo has no public buckets today.

- Watcher checks the hostname of each public bucket against phishing feeds. See [Cargo public buckets](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md#public-buckets).
- Watcher sends a match to Central as a finding with `Phishing:Bucket/Reported` and `bucket` set. See [Reports from Cargo](#reports-from-cargo).
- Central opens a case for the team that owns the bucket.
- Central can suspend the bucket with `suspend_bucket`, and lift the suspension with `unsuspend_bucket`. See [Calls to Cargo](#calls-to-cargo).

### Mining

The AUP forbids mining on every server, trial or paid. CPU use alone is never evidence. Watcher finds mining from the stratum counter, and from mining pool matches in the NAT and SNI logs. See [Cargo finding codes](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#finding-codes).

| Team | Outcome |
|---|---|
| Trial, or never paid | Isolate |
| Paid | Quarantine, 24 h deadline |
| A repeat in 90 days | Isolate. An operator decides on `Team.suspend`. |

Isolation is enough: a miner with no network earns nothing.

### Self-quarantine

A button on the server's Security tab applies `quarantine` with `applied_by = Customer`. Access through the WireGuard gateway stays. The customer can lift it. Both actions need `security:manage`.

### Inbound DDoS

The customer is the victim. The steps protect the customer. They are not penalties and never count as history.

- On a `DoS:VM/InboundFlood` finding, Central applies `ingress_throttle` to the VM. See [Cargo thresholds](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#thresholds).
- An operator can add an XDP drop on the attacked address, or withdraw the address, in Atlas. See [Atlas inbound DDoS](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md#inbound-ddos).
- Central sends `security_inbound_attack`: "Your server is under attack. We limited inbound traffic to X."
- Central tells customers with a public IP to put their sites behind the proxy.
- After an operator withdraws an attacked IP, Central shows the new address that Atlas reports.

## Public IP history

Central records each change of `public_ipv4` or `public_ipv6` on a Virtual Machine in a Public IP Assignment. Report attribution uses it. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#public-ip-assignment).

- The Virtual Machine controller writes the rows when Central records the observed state from Atlas, in the same way as `sync_public_ipv4_billing`.
- A new address opens a row with `attached_at`. A removed or changed address closes the open row with `detached_at`. A Terminated server closes its open rows.
- Rows are append only. Only `detached_at` changes.
- The times are when Central records the change. They can be late by the state delivery delay.
- Attribution finds the row where `attached_at <= t < detached_at`, or where `detached_at` is empty.
- Each day without this record loses history, so it comes first in the implementation.

A shared NAT address names no single server. For it, Central calls Cargo `attribute_address`. See [Calls to Cargo](#calls-to-cargo).

## Report intake

Abuse reports live only in Central.

### Channels

| Channel | Path |
|---|---|
| Email | `abuse_email`, read by a Frappe incoming Email Account. The same address is the IRT and `abuse-c` contact in APNIC WHOIS for our prefixes. |
| Web form | Guest page `/abuse`: category, address or hostname, port, time with timezone, description, and evidence upload. hCaptcha, a rate limit for each IP, and an upload size limit. |
| Feeds | Watcher matches feeds. A match is a finding, not a report. Central sends no reply. See [Findings from Watcher](#findings-from-watcher). |
| Legal | Law enforcement requests, court orders, and CERT-In directions. A responder forwards them to legal and links them to the case. Never automatic. |

### Abuse Report

A standalone DocType. It is not team-scoped. Only `Abuse Responder` reads it. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-report).

- Status: New, Attributed, Partly Attributed, Unattributed, Duplicate, or Rejected.
- Each item (address or hostname, port, time) has its own attributed server, attribution method, and `abuse_case`. One report can name servers of different teams.

### Processing

1. Parse X-ARF, ARF (RFC 5965), Shadowserver, and Spamhaus formats. For other text, extract addresses, hostnames, and times, and send the report to a responder to check.
2. Drop loops and noise:
   - Send no auto-reply to a message with `Auto-Submitted` other than `no` (RFC 3834), to bounces, or to `mailer-daemon`.
   - A subject with a case reference, for example `[AC-00192]`, joins that case.
   - Accept at most 20 reports from one reporter in one hour. Hold later ones for a responder.
3. Attribute each item:
   - Hostname: Central site records (Site Domain) first, then proxy routes. Method Site Record or Proxy Route.
   - Dedicated address: the [Public IP Assignment](#public-ip-history) row for the address and time. Method Public IP History.
   - Shared NAT address: Cargo `attribute_address` with the address, port, and time. Method NAT Log. See [Calls to Cargo](#calls-to-cargo).
   - Proxy address: the hostname in the report, as above. Without a hostname, the item is `Unattributed`.
   - No match: `Unattributed`, to the dashboard queue. Never guess.
4. Merge: an item for a server with an open case of the same category joins that case. Ten complaints make one case and one notice.
5. Set `reporter_trust`:
   - Trusted: a sender in `trusted_reporters`.
   - Known: a sender with earlier confirmed reports.
   - Unknown: all other senders.
6. Act. A report alone gives only `abuse_notice`. A restriction needs a Trusted reporter, or an Abuse Signal of the same kind on the same server within 24 h of the reported time. Illegal content goes straight to a responder through `#abuse-p1`.

### Replies to reporters

- On receipt: one auto-reply with the reference, from `abuse_email`. No reply to automated notices from Trusted reporters.
- On close: "We have reviewed your report and taken appropriate action", or "We could not find a server of ours at that address and time".
- A reply never holds the customer's name, team, plan, or action details.
- Reporter replies join the case thread.

### Redaction

The customer gets the reporter's evidence lines (log lines, spam headers, URLs) in `customer_evidence`. Central removes the reporter's name, email, addresses, and mail headers. A responder can edit the text before the notice goes out. Central never forwards raw attachments.

## Customer messages

All customer messages come from Central through `central/notification/engine.py`. There are no customer webhooks. Email, in-app notifications, and the dashboard are enough.

### Engine changes

| Change | Today |
|---|---|
| New category `Security` in `Notification Event Type.category` | Billing, Server, Team, Trial |
| High and Critical cases use severity `Error`. Others use `Warning` or `Info`. No new level. | Info, Success, Warning, Error |
| Security email cannot be turned off. The preferences page shows it as always on. | `_email_enabled` allows opt-out of any category |
| A team security contact gets Security events only. It is one address and need not be a member. | Email goes only to members |
| Central records each send on the case `notifications` table | Best effort, Error Log on failure |

Recipients of Security email:

- The team owner.
- Members with `security:view`.
- The security contact, `Team.security_contact_email`. See [Team security contact](#team-security-contact).

### Events

| Event | When | Severity | Channels |
|---|---|---|---|
| `abuse_notice` | New case, no restriction | Warning | In-app, email |
| `abuse_action_required` | Case with a deadline | Error for High or Critical, else Warning | In-app, email, banner |
| `abuse_restriction_applied` | A restriction is applied | Error for High or Critical, else Warning | In-app, email, banner |
| `abuse_deadline_reminder` | At 50% of the deadline, and 2 h before it | Warning | In-app, email |
| `abuse_restriction_lifted` | A restriction is lifted or expires | Info | In-app |
| `abuse_case_resolved` | Case closed | Info | In-app, email |
| `security_inbound_attack` | The customer is a DDoS target | Warning | In-app, email |
| `smtp_unblock_decided` | A Port 25 Request is accepted, rejected, or revoked | Info | In-app, email |

- An extension of a restriction sends no new email.
- `_is_duplicate` uses the case as the reference.

### Content

Each email has:

1. What we saw, in words. Example: "Your server `acme-prod` (BOM) opened connections to 4,312 addresses on port 22 between 10:02 and 10:14 UTC. Fewer than 3% answered." Addresses are truncated to /24.
2. What it likely means. Start from compromise, not blame.
3. What we did, and until when.
4. What to do, with a link to the guide for the finding code.
5. The deadline, and what happens at it.
6. How to respond: a button to the case. Email replies with `[AC-00192]` in the subject reach the case.
7. Redacted report evidence, if any. See [Redaction](#redaction).

The platform docs have one guide for each finding code. Write the guide before the code goes live.

R2 and R3 notices also say: "If you operate in India, you may have your own duty to report this to CERT-In." See [CERT-In](CERT_IN.md#tiers).

### Deadlines

- The deadline starts when Central sends the first email to the owner or the security contact.
- If Central cannot send a customer notice, the case goes to `Notification Failed`, the deadline does not start, and `#abuse` gets an alert. Automatic restrictions still apply.
- A responder can mark a notice as delivered by another channel. This starts the deadline.
- At the deadline, the policy engine takes the next ladder step and sends `abuse_restriction_applied`.

### Dashboard

- Security tab on each server: active restrictions and their expiry, open cases, the signal timeline, self-quarantine, the port 25 request, and the exception request. Self-quarantine and the requests need `security:manage`.
- Team abuse cases page.
- Case page: acknowledge, describe the fix, self-lift or request a lift, or dispute. These responses need `security:manage`. Each response alerts the operator queue.
- A banner in `AppShell.vue` when any server has a High or Critical case, next to `SuspendedTeamNotice.vue`.
- The `team_suspended` email states the reason.

The dashboard API returns only the case fields and a redacted signal list. It never returns the operator or CERT-In fields.

## Team security contact

`Team.security_contact_email` and `Team.security_contact_name` are optional. The contact gets Security events only. Owners and admins edit them on the dashboard team settings page. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#team-layout-change).

## Operations

Responders hold the Desk role `Abuse Responder`.

### Settings

Central Settings has a tab "Abuse". No field has a default. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#central-settings-tab-abuse-layout-change).

| Field | Use |
|---|---|
| `abuse_email` | Report intake, reporter replies, CERT-In reports, and operator alert email. Example: abuse@example.com. |
| `abuse_alert_webhook_url` | Raven `#abuse-p1` |
| `abuse_report_webhook_url` | Raven `#abuse` and the daily digest |
| `trusted_reporters` | Domains and addresses whose reports are Trusted |
| `cert_in_contact_*` | Name, designation, organisation, address, email, mobile, phone, and fax (optional). CERT-In Annexure II. |
| `cert_in_incident_email` | The address that gets CERT-In reports |

When a field is empty:

- Central does not guess and has no fallback.
- The abuse dashboard shows a red banner that names the field. The readiness checks fail, as in `central/billing/platform/readiness.py`.
- Central does not send a message that needs the field. It writes an Error Log and sets `has_operator_notification_failure` on the case. The case status does not change.
- "Build report" refuses until the CERT-In contact fields are set.
- Customer notices still go out.

The profile multipliers are constants, not settings. See [Profiles](#profiles).

### Channels

| Channel | Gets |
|---|---|
| Email to `abuse_email` | Every Critical case, copies of reporter acknowledgements, CERT-In clock alerts |
| Raven `#abuse-p1` (pages on call) | Critical findings, region-level floods, illegal content, unconfirmed cases past their SLA, CERT-In clocks with 2 h left |
| Raven `#abuse` | Cases that need a person (dispute, port 25 review, failed attribution, deadline reached on a paid team, `Notification Failed`, a `Failed` restriction), DNSBL listings with no case, log integrity findings (no case), and regions where Watcher does not report. See [Monitoring](#monitoring). |
| Daily digest | Cases opened and closed, restrictions applied, top findings, shadow signals and false positives by finding code, DNSBL listings |

### Abuse dashboard

A Desk workspace `Abuse` in Central, with Insights charts. Central sees all regions, teams, and cases.

```text
┌ Abuse ─────────────────────────────────────────────── Region: All ▾  Last 7 days ▾ ┐
│ Open 14  Critical 2  Awaiting customer 7  Overdue 1  CERT-In clocks 1 (3h 12m)      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ SLA left  Sev   Case      Team           Region  Finding               Level        │
│ 0:41      Crit  AC-00192  acme-trial-31  BOM     DoS:VM/OutboundFlood  Isolate      │
│ 2:10      High  AC-00190  foo-pvt        BLR     Recon:VM/Portscan     Port block   │
├──────────────────────────┬───────────────────────────┬──────────────────────────────┤
│ Signals by finding       │ Shadow signals by finding │ Public IPv4 on DNSBLs: 3     │
│ Cases opened vs closed   │ Finding lag by region     │ False positives (7 d): 1     │
├──────────────────────────┴───────────────────────────┴──────────────────────────────┤
│ Unattributed reports 4   Port 25 requests 2   Disputes 1   Restrictions > 14 days 0 │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

Case view:

- Evidence pack: the signal timeline, with the measured value, the threshold, and the evidence of each finding. See [Signals](#signals).
- Team context: trust tier, age, paid history, earlier cases, and security contact.
- One button for each ladder step. Each needs a reason and writes a Resource Action and a Comment.
- Separate threads with the customer and the reporter, with reply templates. Neither sees the identity of the other.
- The CERT-In panel. See [CERT-In](CERT_IN.md#workflow).

### SLA

| Severity | First action within |
|---|---|
| Critical | 1 h |
| High | 4 h |
| Others | 1 business day |

### Monitoring

- `track_changes` is on for Abuse Case, Abuse Exception, Abuse Signal, and Port 25 Request. Central Resource Actions and Abuse Case Restriction rows are the audit record of who restricted a VM and why. For an emergency restriction, the Comment on the Atlas Virtual Machine is the record.
- The Central investigator agent gets read tools for abuse cases.
- The abuse dashboard shows the finding lag of each region in "Finding lag by region": the age of each `checked_until` value in the last `abuse` report of the region.
- Central posts to Raven `#abuse` when a region sends no `abuse` report for 10 min, when `checked_until.metrics` or `checked_until.logs` is more than 15 min old, or when `checked_until.feeds` is more than 2 h old. See [Reports from Cargo](#reports-from-cargo).

## Interfaces

All Atlas changes are optional fields or new endpoints. There is no new API version. Central calls other planes only from `central/integrations/`. The Atlas side of this contract is in [Atlas abuse contract](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md).

### Communication

| Caller to receiver | Use | Credential |
|---|---|---|
| Central to Atlas | The restriction API, the port 25 API, the create fields, and `GET` VM for the repair scan. See [Calls to Atlas](#calls-to-atlas). | `atlas-admin:<region>` token, as for every Central call to Atlas |
| Central to the proxy | `suspend_site`. See [Calls to the proxy](#calls-to-the-proxy). | `atlas-proxy:<region>` token |
| Central to Cargo, buckets | `suspend_bucket` and `unsuspend_bucket`. See [Calls to Cargo](#calls-to-cargo). | `atlas-cargo:<region>` token with scope `bucket:*` |
| Central to Cargo, attribution | `attribute_address`. See [Calls to Cargo](#calls-to-cargo). | `atlas-cargo:<region>` token with scope `abuse:attribute` |
| Cargo Watcher to Central | The `abuse` report. See [Reports from Cargo](#reports-from-cargo). | Signed webhook delivery, checked against `Region.cargo_webhook_secret` |

Atlas sends no abuse event to Central. Central reads restrictions from the Atlas `GET` VM response. See [Restriction states](#restriction-states).

The platform [service access matrix](https://frappe.github.io/platform/reference/token-validation) needs the same Central to Cargo attribution row.

### Calls to Atlas

Central calls these through `central/integrations/atlas.py`. Each one is `central_only`. Atlas serves each one under the per-VM network lock: it reads the network object from Metal, merges one change, and sends the complete object back. See [Atlas restriction API](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#restriction-api) and [Atlas port 25 API](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#port-25-api).

| Call | Use |
|---|---|
| `PUT /api/atlas/virtual-machines/<id>/restrictions` | Apply a restriction. Idempotent by `idempotency_key`. See [Apply a restriction](#apply-a-restriction). |
| `PATCH /api/atlas/virtual-machines/<id>/restrictions/<restriction_id>` | Extend a level 2 restriction with a new `expires_at`, while the match continues and less than 12 h remain. Only `expires_at` changes. See [Policy engine](#policy-engine). |
| `DELETE /api/atlas/virtual-machines/<id>/restrictions/<restriction_id>` | Lift a restriction by its ID. Lifting a missing entry succeeds. |
| `PUT /api/atlas/virtual-machines/<id>/port-25` | Set or clear the port 25 block with `is_blocked`. See [Email](#email). |

- `restriction_id` is the `idempotency_key` of the apply call, or the `atlas-` ID of an emergency restriction.
- The response of each call holds the `restrictions` list of the VM, `is_port_25_blocked`, and `desired_generation`, `observed_generation`, and `host_error` from Metal. Central stores `desired_generation` on the row and sets its state from the response. See [Restriction states](#restriction-states).
- Atlas refuses a call on a VM of tenant 0 with HTTP 403. Central never sends one, because it does not know these VMs.
- On a Metal host without restriction support, Atlas answers `409 host_unsupported` and saves nothing. Central sets the row to `Failed`. Other errors keep the row `Pending`. See [Restriction states](#restriction-states).

Changed requests, with optional fields:

| Request | Field |
|---|---|
| VM create | Create fields that Atlas puts in the Metal network object: `is_port_25_blocked: true` on every create, and `restrictions` (inherited, each with `idempotency_key` and `case_reference`). See [New servers](#new-servers). |
| `GET` VM response | `restrictions`, `is_port_25_blocked`, `desired_generation`, `observed_generation`, and `host_error`. Central's repair scan reads them. See [Restriction states](#restriction-states). |

Before Central terminates a server with an open case or an active restriction, it takes a snapshot of the disk through the existing Atlas snapshot action. The snapshot is a VM Snapshot with `is_abuse_evidence` set. Central keeps it for 30 days, or longer on a legal hold. The customer dashboard never lists it, and the customer cannot delete it. Only `Abuse Responder` and System Manager read it. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#vm-snapshot-layout-change).

#### Apply a restriction

Central sends:

| Field | Value |
|---|---|
| `idempotency_key` | The name of the Resource Action for the restriction. Atlas uses it as the entry ID. |
| `case_reference` | The Abuse Case name, for example `AC-00192` |
| `kind` | `egress_throttle`, `ingress_throttle`, `port_block`, `quarantine`, or `isolate` |
| `parameters` | For `port_block`: `ports`, each with a `port` and a `protocol`. For a throttle: `pps` and `bps`. |
| `expires_at` | Optional. Metal skips the entry after this time. |

```json
{
	"idempotency_key": "8f3k2m1q9a",
	"case_reference": "AC-00192",
	"kind": "port_block",
	"parameters": {"ports": [{"port": 25, "protocol": "tcp"}, {"port": 465, "protocol": "tcp"}, {"port": 587, "protocol": "tcp"}]},
	"expires_at": "2026-10-30T10:14:00Z"
}
```

Atlas answers with the VM network fields:

```json
{
	"restrictions": [
		{
			"id": "8f3k2m1q9a",
			"kind": "port_block",
			"parameters": {"ports": [{"port": 25, "protocol": "tcp"}, {"port": 465, "protocol": "tcp"}, {"port": 587, "protocol": "tcp"}]},
			"expires_at": "2026-10-30T10:14:00Z",
			"case_reference": "AC-00192"
		}
	],
	"is_port_25_blocked": true,
	"desired_generation": 42,
	"observed_generation": 41,
	"host_error": null
}
```

- When the entry is in `restrictions`, Central sets the row to `Saved` and stores `desired_generation`. The repair scan sets it to `Applied` later.
- A repeat with the same `idempotency_key` returns the existing entry and changes nothing.
- A lost response leaves the row `Pending` and the Resource Action uncertain. The repair scan settles it. Central does not send a second apply with a new key.

### Calls to the proxy

Through `central/integrations/proxy.py`:

- `suspend_site(name, reason_code)`: sets the abuse tombstone on a site route.

### Calls to Cargo

Central calls these through `central/integrations/cargo.py`:

- `attribute_address(address, port, time)`: returns the Atlas VM ID that used a shared NAT address and port at that time, or nothing. Watcher reads the NAT log for it. Report attribution uses it. See [Processing](#processing) and [Cargo attribution](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#attribution).
- `suspend_bucket(name, region, reason_code)`: turns off website access on a public bucket. The bucket and its objects stay.
- `unsuspend_bucket(name, region)`: turns website access on again.

Central sends a token for that region's Cargo in each call:

- The bucket calls use the `atlas-cargo:<region>` token with scope `bucket:*` from `mint_cargo_token` in `central/sso.py`.
- `attribute_address` uses an `atlas-cargo:<region>` token with the new scope `abuse:attribute`. A new function in `central/sso.py` mints it with `_mint_regional_token`, in the same way as `mint_cargo_token`. It has the same 5 min TTL and the same signing key as `mint_cargo_token`, with `iss` = `central`.
- Cargo accepts `attribute_address` only with a token that Central signed with scope `abuse:attribute`. It refuses a token that Atlas issued, and every other scope, with HTTP 403.

Central never reads the log bucket or Datum. Log rows stay in the region, because SNI rows can be personal data.

### Reports from Cargo

Watcher sends findings in a Cargo report with `service` set to `abuse`. The signature, headers, and retries are those of every Cargo report. See [Cargo reports](WEBHOOKS.md#cargo-reports). The report also carries `region` and `region_id`, as every Cargo report does. Central ignores them, as that section says. Central owns this shape. Watcher documents when it sends a finding. See [Cargo findings](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#findings).

| Field | Value |
|---|---|
| `service` | `abuse` |
| `checked_until` | An object with one timestamp for each input: `metrics`, `logs`, and `feeds`. `metrics` and `logs` are the end of the last window that Watcher checked from that input. `feeds` is the end of the last hourly address check. |
| `findings` | The list of new and changed findings. It can be empty. |

The `abuse` report has no `status` and no `service_endpoint`. `accept_cargo_report` in `central/integrations/state_delivery.py` handles it in its own branch, before the status check. Central writes no Service Detail row for it.

- Watcher sends an `abuse` report after each run, every minute. It sends the report also when it has no new or changed finding.
- When an input fails, Watcher writes an Error Log and does not move `checked_until` for that input.
- Central keeps the receipt time and `checked_until` of the last `abuse` report of each region. It alerts when they are old. See [Monitoring](#monitoring).

Each finding has these fields:

| Field | Value |
|---|---|
| `finding_id` | The Watcher ID of the finding. Central matches repeats on it. |
| `finding_code` | A code from [Cargo finding codes](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#finding-codes) |
| `severity` | Low, Medium, High, or Critical, from the Abuse Threshold Trigger row that matched |
| `virtual_machine` | Optional. The Atlas VM ID, when Watcher knows it. Central matches it to `Virtual Machine.atlas_vm_id`. A finding on a dedicated public address has it. A finding on a shared NAT address does not. |
| `bucket` | Optional. The bucket name, when the subject is a bucket. |
| `hostname` | Optional. The hostname, when the subject is a hostname. |
| `address` | Optional. The public address, when the subject is an address. |
| `window_start` | The start of the window |
| `window_end` | The end of the window |
| `measured` | An object with one measured value for each volume trigger of the rule. Empty for a feed match or a stratum match. See [Profiles](#profiles). |
| `threshold` | An object with the standard threshold for each volume trigger in `measured`. Empty for a feed match or a stratum match. |
| `evidence` | An object. See the evidence fields below. No payloads. |
| `is_shadow` | Set when the Abuse Threshold of the finding code is in Shadow mode |
| `is_trusted_source` | Set when the finding comes from an Abuse Feed with `is_trusted` |

Each evidence field is optional:

| Field | Value |
|---|---|
| `port_class` | The port class of the traffic |
| `ports` | A list of port numbers |
| `protocol` | The protocol, for example `tcp` |
| `counts` | An object of counts |
| `ratios` | An object of measured ratios, for example `answered_percent` |
| `prefixes` | Destination prefixes, truncated to /24 for IPv4 and /48 for IPv6 |
| `feed` | The name of the Abuse Feed that matched |
| `hostname_match` | The feed entry that matched |
| `writer` | The log writer, for an `Integrity:Log/Missing` finding |
| `objects` | The log objects that are missing or changed |
| `change` | `missing`, `changed` or `deleted` |

```json
{
	"region": "bom",
	"region_id": 3,
	"service": "abuse",
	"checked_until": {"metrics": "2026-10-29T10:03:00Z", "logs": "2026-10-29T10:00:00Z", "feeds": "2026-10-29T10:00:00Z"},
	"findings": [
		{
			"finding_id": "fnd-7f3a",
			"finding_code": "Recon:VM/Portscan",
			"severity": "Medium",
			"virtual_machine": "vm-0a1b2c3d4e",
			"window_start": "2026-10-29T10:02:00Z",
			"window_end": "2026-10-29T10:03:00Z",
			"measured": {"destinations": 4312},
			"threshold": {"destinations": 256},
			"evidence": {"port_class": "auth", "ports": [22], "ratios": {"answered_percent": 3}, "prefixes": ["203.0.113.0/24"]},
			"is_shadow": false,
			"is_trusted_source": false
		}
	]
}
```

- A continuing match sends the same `finding_id` with a later `window_end`. Central updates the same Abuse Signal. See [Signals](#signals).
- Central finds the team from the VM, the bucket, the hostname, or the address. See [Findings from Watcher](#findings-from-watcher).
- Central skips a finding on a VM that it does not know. It writes an Error Log for a bucket or a hostname that it does not know, and opens no case.
- An `Integrity:Log/Missing` finding names a log writer, not a VM. Its `evidence` has `writer`, `objects` and `change`. Central stores it as an Abuse Signal with no server, posts it to Raven `#abuse` as High, and opens no case. See [Cargo log integrity](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#log-integrity).
- Central builds a `port_block` from `port_class` or `ports` in `evidence`.
- Central applies the [profile](#profiles) and any [exception](#exceptions). A finding with `is_shadow` is stored with no action.
- An older Central answers `unsupported service 'abuse'` with HTTP 200 and drops the report. So Central must accept `abuse` reports before Watcher sends them. See [Deploy order](#deploy-order).

## Records and retention

| Record | Retention |
|---|---|
| Abuse Case | 3 years after close. 5 years, or until the hold ends, with a CERT-In report or a legal hold. |
| Abuse Signal | 2 years. A signal that a case links stays as long as the case. |
| Public IP Assignment | 2 years after `detached_at` |
| Abuse Report raw message | 1 year after the case closes. The parsed fields stay. |
| Abuse Report that was never attributed | 90 days |
| Evidence snapshot of a terminated server | 30 days. Longer on a legal hold. |

Deletion jobs follow `clear_old_logs` (Log Settings), so all Central periods are visible and editable in one place.

Datum keeps the per-VM metrics for 30 days. The log bucket keeps the logs for 180 days. See [Cargo abuse logs](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md). Atlas keeps no restriction record. An entry stays in the Metal VM network object until Central or an Atlas operator lifts it, or until Atlas removes it after its `expires_at`. The Abuse Case Restriction rows and the Resource Actions keep the history in Central.

### Legal hold

- `is_legal_hold` on the case keeps the case and its signals past their normal retention.
- A legal hold keeps the evidence snapshot of a terminated server past 30 days.
- A site under a legal hold gets HTTP 451 from the proxy.

### Deletion

Abuse Case, Abuse Signal, and Abuse Exception link Team and Server. These links would block `Team.on_trash`. On team or server deletion, Central:

1. Copies the team name, the owner email, and the server name into plain fields.
2. Clears the links.

The owner email lets responders find a repeat offender who signs up again.

Public IP Assignment stores the team and the server as plain names, so it never blocks a deletion.

Central deletes Port 25 Requests with their team or server. They hold no evidence. A revoked request's cause stays on its Abuse Case.

Evidence holds no payloads. Addresses shown to customers are truncated to /24.

## Deploy order

1. The Datum release: the per-VM table with its 30-day TTL, the ingest that routes `vm_abuse_*` series to that table, and the `watcher` read user. See [Cargo per-VM metrics](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md#per-vm-metrics). Cargo: the log bucket, the `permission` argument of `add_credentials`, and the `abuse:attribute` scope check on `attribute_address`.
2. Atlas app: the restriction API and the port 25 API, the `restrictions` and `is_port_25_blocked` create fields, the log write key provisioning, and the Atlas Settings fields. A patch makes a write key for each existing Metal host and proxy node and writes it into their config. See [Atlas log bucket keys](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#log-bucket-keys).
3. Metal: `restrictions` and `is_port_25_blocked` in the VM network object, the `metal_abuse` chain, the counters behind `abuse_metrics`, and the log upload.
4. HTTP proxy: the tombstone and the log upload.
5. Central: the `abuse:attribute` token, the `abuse` report branch, profiles, cases, restrictions, and `is_port_25_blocked` on every VM create.
6. An operator turns on `is_abuse_metrics_enabled` in Atlas Settings. Watcher starts with every Abuse Threshold in Shadow, then goes Active one finding code at a time. See [Cargo calibration](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#calibration).

All Atlas changes are optional fields: an old Central ignores them. Central must accept `abuse` reports before Watcher sends them in step 6, because an older Central drops them. Public IP history has no dependency, so Central can ship it before step 1.

## Compared with AWS

| AWS | Frappe Cloud |
|---|---|
| Port 25 blocked, unblock by form | The same, with the trust tier as a gate. See [Email](#email). |
| Abuse report to the customer, with a deadline | Abuse Case with a deadline and the ladder. See [Report intake](#report-intake) and [Ladder](#ladder). |
| AWS Health abuse event, alternate security contact | Security notifications, the team security contact, and `security:view`. See [Customer messages](#customer-messages). |
| Shield Standard | Inbound DDoS protection and a notice to the customer. See [Inbound DDoS](#inbound-ddos). |

Differences from AWS: each notice holds the exact evidence. Self-quarantine is one click and keeps access through the WireGuard gateway. Automatic restrictions from findings expire by themselves.

## Sources

- AWS port 25: https://repost.aws/knowledge-center/ec2-port-25-throttle
- AWS abuse reports: https://repost.aws/articles/ARZVtmQf5CS_-UPgIJSCyr3A/securing-compromised-ec2-instances-implicated-in-abuse-reports
- AWS Health events: https://docs.aws.amazon.com/eventbridge/latest/ref/events-ref-health.html
- GuardDuty EC2 findings: https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_finding-types-ec2.html
- Hetzner lock reasons: https://docs.hetzner.com/robot/dedicated-server/troubleshooting/guideline-in-case-of-server-locking/
- Hetzner netscan remote trigger: https://forum.torproject.org/t/tor-relays-advisory-unauthenticated-remote-trigger-of-hetzners-netscan-detection/21295
- OVHcloud anti-hack: https://docs.ovhcloud.com/en/guides/bare-metal-cloud/dedicated-servers/anti-hack-dedicated-vps.md
- CERT-In sources: see [CERT-In](CERT_IN.md#sources).
