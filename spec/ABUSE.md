# Abuse protection

## Purpose

This document is the Central part of abuse protection in Frappe Cloud v2. It covers abuse that starts from, or targets, tenant resources in an Atlas region, and the messages to customers and operators about it.

Status: planned. Central does not implement this design yet. The DocType layouts in [Abuse layouts](ABUSE_LAYOUTS.md) need engineer approval before implementation. Change this document before you change the design.

Atlas owns detection and enforcement in the data plane: finding codes, counters, thresholds, circuit breakers, the `metal_abuse` chain, and the Atlas records and logs. See the [Atlas abuse documentation](https://github.com/frappe/atlas/blob/develop/docs/abuse/index.md). Cargo owns the regional log bucket, its object layout, and its keys. See [Cargo abuse logs](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md). CERT-In reporting is in [CERT-In](CERT_IN.md).

## Scope

In scope:

- Outbound abuse from VMs: floods, scans, brute force, spam, reflectors, C2, and crypto mining.
- Hosted content on proxy sites: phishing, malware, and illegal content.
- Inbound DDoS on tenants and on the platform.
- Report intake, customer messages, operator alerts, and CERT-In reporting.

Out of scope:

- 180-day logs for all ICT systems (CERT-In direction (iv)), other than the logs in [Cargo abuse logs](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md).
- Guest spoofing and tenant-to-tenant mesh traffic. WG Mesh `local_vms` and `can_communicate` already stop them.
- A guest-side agent. Guests are untrusted.
- Signup data and identity validation (CERT-In direction (v)).

## Principles

1. Atlas detects and enforces in the data plane. Central owns the customer, every escalation, and every message. Atlas does not know teams, trust tiers, or contacts.
2. Atlas acts alone only to protect the region. Its circuit breakers are narrow and short, and they expire by themselves.
3. Restrictions live in a layer that the tenant API cannot write. Tenant firewall, route, and IPv4 changes cannot widen them.
4. Every restriction has a reason, an actor, a case, and an end condition. Terminate by an operator is the last step.
5. Restrict traffic, never compute. The abuse system never pauses or stops a VM.
6. Keep evidence before it is destroyed. Atlas snapshots the disk before it terminates a VM with an open case or an active restriction. Never stop and start a VM to collect evidence.
7. Detection failure must not block customers. If a detector, Atlas, or Central is down, nothing new is applied, and breakers still expire.
8. Atlas stays backward compatible: optional fields, optional events, and new eBPF maps only. Central deploys first.

## Who does what

| Component | Responsible for | Acts alone |
|---|---|---|
| Metal (each host) | Counters, SNI and NAT logs, detectors, circuit breakers, the `metal_abuse` chain, default blocks | Breakers only |
| Atlas app (each region) | Abuse Signal, VM Restriction, Public IP Assignment, Abuse Settings (thresholds), feeds, attribution, the restriction API, events to Central | Emergency restrictions by an operator only |
| Central | Abuse Case, Abuse Report, Abuse Exception, the policy engine, all customer messages, the abuse dashboard, CERT-In | Yes |
| HTTP proxy | Rate limits, the abuse tombstone, the access log | No. Follows Atlas and Central. |
| IPv6 router | Per-source meter, restriction set | No |
| Cargo | Regional log bucket, phishing feed check on public buckets | No |
| Pilot | Nothing | Not applicable |

```text
Metal host              sync     Atlas app            webhook     Central
counters, logs     ───────────▶  Abuse Signal     ───────────▶   Abuse Case, policy engine
breakers           ◀───────────  VM Restriction   ◀───────────   messages, dashboard
metal_abuse         host config  attribution       central_only  Abuse Report, CERT-In
                                                     API
HTTP proxy: limits, tombstone          Cargo: log bucket (180 days)
```

## Roles and capabilities

| Name | Kind | Use |
|---|---|---|
| `Abuse Responder` | Desk role, planned. Not tied to a team. | Reads and writes Abuse Case, Abuse Report, Abuse Exception, and Port 25 Request. Works the abuse dashboard. |
| `security:view` | Team capability, planned | Reads the team's abuse cases and gets Security email. Owner and Admin roles get it by default. |
| `security:manage` | Team capability, planned | Responds to a case, requests a lift or an exception, applies and lifts self-quarantine, and requests a port 25 unblock. Implies `security:view`. Owner, Admin, and Developer roles get it by default. These are the roles that have `server:network`. |

Add `security:view` and `security:manage` to [Capabilities](../CAPABILITIES.md) and the fixtures in the implementation change. Developer gets `security:view` through the implication. Customers read cases only through the dashboard API, filtered by `security:view`. Each customer action on a case, a restriction, an exception, or a port 25 request needs `security:manage`.

## Abuse Case

An Abuse Case is the record of one abuse problem on one server. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-case).

- Central keeps one open case for each (team, server, finding code), or for each (team, bucket, finding code).
- The name is `AC-.#####`. It is the reference in mail subjects, for example `[AC-00192]`.
- A case gets its signals from Atlas events, from Cargo reports, from Abuse Reports, or from an operator.
- A case for a public bucket names the bucket instead of a server. See [Public buckets](#public-buckets).
- Status, ladder level, deadlines, and restrictions change only through the policy engine or an operator action. Nobody edits them on the form.
- Severity is Low, Medium, High, or Critical. Three breakers of one kind on the case in 24 h raise it to High.

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
| Escalated | The case waits for an operator decision: a dispute, a deadline reached on a paid team, an isolate, or illegal content. | Restricted or Resolved, from the operator decision. |
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
| 0 | Signal | Metal | Not applicable |
| 1 | Notice | Central | Not applicable |
| 2 | Circuit breaker | Metal | Expires or releases |
| 3 | `port_block` or `egress_throttle` | Central or an operator | Lift |
| 4 | `quarantine` | Central or an operator | Lift |
| 5 | `isolate` | Central (trials, confirmed mining) or an operator | Operator only |

- Metal never goes above level 2. Breaker rules are in [Atlas enforcement](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md).
- What each restriction kind blocks is in [Atlas enforcement](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md).
- The ladder stops at isolate. There is no pause and no stop.
- History counts per team over 90 days. A new VM does not reset it.
- When a VM is isolated, Central also tombstones its sites.
- Restrictions add up. Lifting one never lifts another.
- The abuse dashboard lists level 3 to 5 restrictions older than 14 days for review.

Outside the ladder, operators keep `Team.suspend` (fraud, legal hold) and terminate. No policy applies them. Today `Team.suspend` skips `Paused` servers (`central/identity/doctype/team/lifecycle.py`). Fix this before abuse cases depend on it.

### Tracks

The ladder is one track. Three tracks are outside it:

| Track | Applies to | Rule |
|---|---|---|
| Sites | Phishing and illegal content | Central tombstones the site on the proxy. This equals level 4. Only an operator lifts it. |
| Protection | Inbound DDoS on the customer | Steps protect the victim. The dashboard shows them as protection. They never count as history. |
| Defaults | The `smtp_outbound` and `mining_pools` default blocks | Not ladder steps and not history. |

### Lifts

Each customer action below needs `security:manage`.

- Self-lift: once for each case, for level 3 or 4, after the customer writes what they fixed.
- Automatic return: the same finding category on the team within 7 days of a self-lift puts the restriction back, with no new deadline. After that, only an operator lifts it.
- Lift request: for any other restriction, the customer asks on the case page. The response kind is `Lift Requested`. A responder decides.
- Self-quarantine: the customer can apply `quarantine` from the Security tab. See [Self-quarantine](#self-quarantine).

### New servers

While a team has an open case at level 4 or 5, every new server starts with the same restriction. Central sends it in the optional `restrictions` field of the Atlas VM create request. The restriction ends with the case.

### Who changes restrictions

- Normal: the policy engine or an operator in Central calls the restriction API. Central records a Resource Action with action `restrict` (a new action) and a system actor, and links the case.
- Emergency: an `Atlas Admin` creates a VM Restriction in Atlas Desk. Atlas sends `vm.restriction`. Central links the restriction to an open case, or opens a case.
- Expiry: Atlas ends a restriction at `expires_at`. Central records the end from `vm.restriction`.

## Policy engine

`central/abuse/policy.py` picks the next step. Its inputs are the finding, the severity, the Trust Tier Level, the account age, the paid history, and earlier cases.

Default escalation:

| Finding | Escalation |
|---|---|
| Outbound flood, SYN flood | Notice. A repeat in 7 days: quarantine. |
| Scan, brute force | Notice, 24 h deadline |
| `Smtp:VM/BlockedPort25` | Helpful notice: use port 587 or 465 |
| `Spam:VM/Smtp` | Notice. A DNSBL listing: see [DNSBL response](#dnsbl-response). |
| Reflector | Notice with a fix guide |
| Mining | See [Mining](#mining). |
| C2, beaconing | Notice: likely compromise |
| Phishing site | See [Phishing sites](#phishing-sites). |
| Illegal content | A responder through `#abuse-p1`. Tombstone or isolate. Set `is_legal_hold` on the case. |
| Inbound flood | Protection notice. See [Inbound DDoS](#inbound-ddos). |

Example: a scan from a trial that never paid is isolated. The same scan from a Tier 3 team that paid for 12 months gets a notice and 24 h.

At a deadline, the policy engine takes the next ladder step and sends `abuse_restriction_applied`.

Abuse history lowers the trust tier. A resolved case with a fix restores the tier after 90 days.

The finding codes and their meaning are in [Atlas detection](https://github.com/frappe/atlas/blob/develop/docs/abuse/detection.md).

## Abuse profile

Central sets `abuse_profile` on each VM, so Atlas stays free of team data. Central sends it in the VM create request, and in a VM update when the inputs change. The effect of each profile on thresholds is in [Atlas detection](https://github.com/frappe/atlas/blob/develop/docs/abuse/detection.md).

| Profile | For |
|---|---|
| `strict` | Free trial servers, and teams that never paid |
| `standard` | All other servers. An empty value means `standard`. |
| `relaxed` | Trust tier 3 (Advance) or higher, and no case in 90 days |
| `infrastructure` | Privileged tenant 0 VMs. Atlas sets it. Central never sets it. |

When rules overlap, Central uses the first match:

1. A free trial server is `strict`.
2. A team at trust tier 3 (Advance) or higher is `relaxed`. This includes teams without payments that have a manual override.
3. A team that never paid is `strict`.
4. All other servers are `standard`.

## Abuse Exception

An Abuse Exception lets a team change one detection rule on one server for a fixed period. Example: an authorized penetration test. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-exception).

- A member with `security:manage` requests it on the server's Security tab. A responder approves or rejects it.
- Fields: team, server, finding code, effect (a multiplier, or disabled), reason, expiry, and approver.
- The expiry is at most 90 days after the start.
- On approval, Central sends a VM Abuse Override to Atlas in a VM update. Expiry or revocation removes it.
- The controller refuses host safety codes and the default blocks. Port 25 has its own flow. See [Email](#email).

## Controls

Central never reads the content of a VM's traffic. Atlas reads only the TLS server name and, for mining, the first payload bytes of flows to non-standard ports. The AUP and the privacy policy must say so before Atlas turns on the SNI log.

### Email

Port 25 is blocked for every VM by the `smtp_outbound` default block. The submission ports 465 and 587 stay open.

A Port 25 Request holds one unblock request for one server. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#port-25-request).

- Status: Pending, Accepted, Rejected, or Revoked.
- A server has at most one open request. An open request is Pending or Accepted.
- Accepted sets `is_port_25_allowed` on the VM through an Atlas VM update. Revoked clears it.
- `decided_by`, `decided_at`, and `abuse_case` are read only. Central sets them.

Port 25 unblock flow:

1. A member with `security:manage` creates a Port 25 Request on the server's Security tab: purpose, sending domain, reverse DNS name, and bulk-mail policy. The status is Pending.
2. Central accepts the request automatically for trust tier 3 and higher when the team has no open case. Otherwise the request goes to `#abuse`, and a responder accepts or rejects it with a decision reason.
3. Only a server with a dedicated public IPv4 can get an unblock. Shared NAT addresses are never unblocked.
4. On acceptance, Central sets the status to Accepted and sets `is_port_25_allowed` on that VM through an Atlas VM update.
5. The customer sets reverse DNS on the address.
6. Central sends `smtp_unblock_decided` with the result.
7. A responder can revoke an Accepted request. A DNSBL listing or a spam trap hit revokes it automatically. See [DNSBL response](#dnsbl-response).

### DNSBL response

- A DNSBL listing, or an SNDS spam trap hit, on an address with port 25 unblocked opens a case. Central sets the Port 25 Request of the server to Revoked, sets its `abuse_case` to the new case, and clears `is_port_25_allowed`.
- For `Spam:VM/Smtp` with a DNSBL listing, Central applies `port_block` on the smtp and submission port classes. An operator gets the address delisted.
- DNSBL notices that arrive by email become Abuse Reports. See [Report intake](#report-intake).
- Atlas checks the address pool against DNSBLs and puts a released address with a case into a 30-day cool-down. See [Atlas feeds](https://github.com/frappe/atlas/blob/develop/docs/abuse/detection.md#feeds).

### Phishing sites

- Central suspends a site with `proxy.suspend_site(name, reason_code)` in `central/integrations/proxy.py`. The proxy serves a branded suspended page with HTTP 403 for abuse, or HTTP 451 for a legal hold, and a link to the abuse page.
- Central suspends automatically only when the source is a Trusted feed or reporter, or when another signal corroborates it. Otherwise an operator checks first.
- Only an operator lifts a site suspension.
- Central can lower the proxy rate limits for one site during an attack.
- Atlas checks proxy site hostnames against phishing feeds and sends `vm.abuse.signal` with `Phishing:Site/Reported`. See [Atlas feeds](https://github.com/frappe/atlas/blob/develop/docs/abuse/detection.md#feeds).
- Central gives a score to hostnames with brand terms on young teams.

### Public buckets

- Cargo checks the hostname of each public bucket against phishing feeds. See [Cargo public buckets](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md#public-buckets).
- Cargo sends a match to Central in its `storage` report. See [Reports from Cargo](#reports-from-cargo).
- Central opens a case for the team that owns the bucket.
- Central can suspend the bucket with `suspend_bucket`, and lift the suspension with `unsuspend_bucket`. See [Calls to Cargo](#calls-to-cargo).

### Mining

The AUP forbids mining on every server, trial or paid. CPU use alone is never evidence.

| Team | Outcome |
|---|---|
| Trial, or never paid | Isolate |
| Paid | Quarantine, 24 h deadline |
| A repeat in 90 days | Isolate. An operator decides on `Team.suspend`. |

Isolation is enough: a miner with no network earns nothing.

### Self-quarantine

A button on the server's Security tab applies `quarantine` with `applied_by = Customer`. Access through the WireGuard gateway stays. The customer can lift it. Both actions need `security:manage`.

### Inbound DDoS

The customer is the victim. The steps protect the customer. They are not penalties and never count as history. The steps are in [Atlas enforcement](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md).

Central does these parts:

- Sends `security_inbound_attack`: "Your server is under attack. We limited inbound traffic to X."
- Tells customers with a public IP to put their sites behind the proxy.
- After an operator withdraws an attacked IP in Atlas, Central shows the new address that Atlas reports.

## Report intake

Abuse reports live only in Central. Atlas answers attribution queries.

### Channels

| Channel | Path |
|---|---|
| Email | `abuse_email`, read by a Frappe incoming Email Account. The same address is the IRT and `abuse-c` contact in APNIC WHOIS for our prefixes. |
| Web form | Guest page `/abuse`: category, address or hostname, port, time with timezone, description, and evidence upload. hCaptcha, a rate limit for each IP, and an upload size limit. |
| Feeds | Atlas pulls feeds. They are signals with `source = feed`, not reports. Central sends no reply. |
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
   - Hostname: Central site records first, then proxy routes.
   - Address: Central finds the region and calls the Atlas attribution API. See [Calls to Atlas](#calls-to-atlas).
   - No match: `Unattributed`, to the dashboard queue. Never guess.
4. Merge: an item for a server with an open case of the same category joins that case. Ten complaints make one case and one notice.
5. Set `reporter_trust`:
   - Trusted: a sender in `trusted_reporters`.
   - Known: a sender with earlier confirmed reports.
   - Unknown: all other senders.
6. Act. A report alone gives only `abuse_notice`. A restriction needs a Trusted reporter, or an Abuse Signal of the same kind on the same VM within 24 h of the reported time. Illegal content goes straight to a responder through `#abuse-p1`.

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
| `abuse_restriction_applied` | A restriction, or the first breaker on a case | Error for High or Critical, else Warning | In-app, email, banner |
| `abuse_deadline_reminder` | At 50% of the deadline, and 2 h before it | Warning | In-app, email |
| `abuse_restriction_lifted` | A restriction is lifted or expires | Info | In-app |
| `abuse_case_resolved` | Case closed | Info | In-app, email |
| `security_inbound_attack` | The customer is a DDoS target | Warning | In-app, email |
| `smtp_unblock_decided` | A Port 25 Request is accepted, rejected, or revoked | Info | In-app, email |

Breakers:

- The first breaker on a case sends email.
- Later breakers on the same case within 24 h show in-app only.
- A breaker with no case shows in-app only.
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

### Channels

| Channel | Gets |
|---|---|
| Email to `abuse_email` | Every Critical case, copies of reporter acknowledgements, CERT-In clock alerts |
| Raven `#abuse-p1` (pages on call) | Critical findings, region-level floods, illegal content, attacks on the platform, unconfirmed cases past their SLA, CERT-In clocks with 2 h left |
| Raven `#abuse` | Cases that need a person (dispute, port 25 review, failed attribution, deadline reached on a paid team, `Notification Failed`), and signals from tenant 0 VMs. Atlas also posts host safety alerts here. See [Monitoring](#monitoring). |
| Daily digest | Cases opened and closed, breakers fired, top findings, DNSBL listings, clean free IPv4 count |

### Abuse dashboard

A Desk workspace `Abuse` in Central, with Insights charts. Central sees all regions, teams, and cases.

```text
┌ Abuse ─────────────────────────────────────────────── Region: All ▾  Last 7 days ▾ ┐
│ Open 14  Critical 2  Awaiting customer 7  Overdue 1  CERT-In clocks 1 (3h 12m)      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ SLA left  Sev   Case      Team           Region  Finding               Level        │
│ 0:41      Crit  AC-00192  acme-trial-31  BOM     DoS:VM/OutboundFlood  Isolate      │
│ 2:10      High  AC-00190  foo-pvt        BLR     Recon:VM/Portscan     Breaker      │
├──────────────────────────┬───────────────────────────┬──────────────────────────────┤
│ Signals by finding       │ Active breakers by host   │ IPv4 on DNSBLs: 3 of 412     │
│ Cases opened vs closed   │ Breaker storm: none       │ In cool-down: 9              │
├──────────────────────────┴───────────────────────────┴──────────────────────────────┤
│ Unattributed reports 4   Port 25 requests 2   Disputes 1   Restrictions > 14 days 0 │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

Case view:

- Evidence pack: the signal timeline (Low signals read on demand), `get_vm_metrics` graphs, and NAT, SNI, and proxy log lines. Central fetches them through `central/integrations/atlas.py`.
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

- `track_changes` is on for Abuse Case, Abuse Exception, and Port 25 Request. Atlas VM Restriction rows and Central Resource Actions are the audit record of who restricted a VM and why.
- The Central investigator agent gets read tools for abuse cases.
- The Insights dashboard "Abuse Protection" shows the split of live servers by abuse profile, from Central data. Keep its queries cheap: they share the live-query limit with the Atlas alerts.
- Atlas alerts on detector health and breaker storms. See [Atlas abuse documentation](https://github.com/frappe/atlas/blob/develop/docs/abuse/index.md).
- Host safety stays in Atlas. Atlas records it in telemetry, and an Insights alert posts it to Raven `#abuse`. Central gets no event and opens no case.

## Interfaces

All Atlas changes are optional fields, optional events, or new endpoints. There is no new API version. Central calls other planes only from `central/integrations/`. The producer contract is in [Atlas abuse contract](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md).

### Events from Atlas

Atlas sends two new events through the signed webhook path to `central.api.state_delivery.receive`. See [Inbound webhooks](WEBHOOKS.md) for the signature, headers, and retries. The event fields are in [Atlas events to Central](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#events-to-central).

| Event | Central matches on | Central stores | Central does |
|---|---|---|---|
| `vm.abuse.signal` | `signal_id` = `atlas_signal_id` | Finding code, severity, `window_start`, `window_end`, count, circuit breaker | Finds or opens the case for (team, server, finding code), adds or updates the Abuse Case Signal row, and runs the policy engine |
| `vm.restriction` | `restriction_id` = `atlas_restriction_id` | Kind, `status` (Pending, Applied, Lifted, Failed), expiry, `applied_by`, `applied_by_user` | Adds or updates the Abuse Case Restriction row. An emergency restriction links to an open case or opens one. |

- `state_delivery._decide` and `apply_atlas_report` accept both events.
- A repeated event with the same ID updates the same row. It never adds a second row.
- Only signals for tenant 0 VMs go to Raven `#abuse`. Central opens no case for them.
- Host safety findings do not come to Central. See [Monitoring](#monitoring).
- Atlas decides which signals to send. Shadow signals are never sent.
- Today Central ignores unknown events with HTTP 200. So Central can deploy before Atlas.

### Calls to Atlas

Central calls these through `central/integrations/atlas.py`. Each one is `central_only`.

| Call | Use |
|---|---|
| `PUT /api/atlas/virtual-machines/<id>/restrictions` | Apply a restriction. Idempotent by `idempotency_key`. See [Apply a restriction](#apply-a-restriction). |
| `DELETE /api/atlas/virtual-machines/<id>/restrictions/<name>` | Lift a restriction. Idempotent. |
| `PUT /api/atlas/virtual-machines/<id>/abuse-hold` | Set or clear `has_open_abuse_case`, and an optional legal hold that keeps the evidence snapshot. Idempotent. |
| `GET /api/atlas/virtual-machines/<id>/abuse-signals` | Signals for the evidence pack, Low included |
| `POST /api/atlas/abuse/attributions` | Map a list of (address, port, time) to a VM ID and a method (Public IP History, NAT Log, Proxy Route), or `unknown` |

Changed requests and responses, with optional fields:

| Request | Field |
|---|---|
| VM create | `abuse_profile`, `restrictions` (inherited, see [New servers](#new-servers)) |
| VM update | `abuse_profile`, `abuse_overrides`, `is_port_25_allowed` |
| `GET` VM and `PATCH .../network` responses | `restrictions` (kind, reason code, expiry) |

Central sets the abuse hold when a case opens and clears it when the case closes. A case with `is_legal_hold` sends the legal hold in the same call.

#### Apply a restriction

Central sends:

| Field | Value |
|---|---|
| `idempotency_key` | The name of the Resource Action for the restriction |
| `case_reference` | The Abuse Case name, for example `AC-00192` |
| `kind` | The restriction kind |
| `port_classes` or `ports` | For `port_block` only. Port classes by name (`smtp`, `submission`, ...), or port numbers. |

Atlas returns the restriction name. Central stores it in `atlas_restriction_id` and uses it to lift the restriction. A repeat with the same `idempotency_key` returns the same name. The full request is in [Atlas API](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#atlas-api).

### Calls to the proxy

Through `central/integrations/proxy.py`:

- `suspend_site(name, reason_code)`: sets the abuse tombstone on a site route.
- Per-site rate limits: Central can lower them during an attack.

### Calls to Cargo

Central does not read the log bucket. An operator copies the log bucket keys from Cargo into Atlas Abuse Settings. See [Cargo keys](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md#keys).

For public buckets, Central calls these through `central/integrations/cargo.py`:

- `suspend_bucket(name, region, reason_code)`: turns off website access on the bucket. The bucket and its objects stay.
- `unsuspend_bucket(name, region)`: turns website access on again.

### Reports from Cargo

Cargo reports a phishing match on a public bucket in its existing `storage` report. See [Cargo reports](WEBHOOKS.md#cargo-reports). The report gets a new optional list, `abuse_signals`. Central owns this shape.

| Field | Value |
|---|---|
| `signal_id` | The Cargo ID of the signal. Central matches repeats on it. |
| `bucket` | The bucket name |
| `finding_code` | `Phishing:Bucket/Reported` |
| `severity` | Low, Medium, High, or Critical |
| `evidence` | The public hostname and the feed that matched |
| `window_start` | The start of the check |
| `window_end` | The end of the check |

```json
{
	"service": "storage",
	"status": "Available",
	"abuse_signals": [
		{
			"signal_id": "sig-7f3a",
			"bucket": "acme-assets",
			"finding_code": "Phishing:Bucket/Reported",
			"severity": "High",
			"evidence": "acme-assets.s3.example.com in OpenPhish",
			"window_start": "2026-10-29T10:00:00Z",
			"window_end": "2026-10-29T10:05:00Z"
		}
	]
}
```

- Central finds the team of the bucket, finds or opens the case for (team, bucket, finding code), and adds or updates an Abuse Case Signal row by `cargo_signal_id`.
- Central writes an Error Log for a signal on a bucket that it does not know. It opens no case for it.
- Today Central ignores unknown fields in a Cargo report. So Cargo can send the list before Central reads it.

## Records and retention

| Record | Retention |
|---|---|
| Abuse Case | 3 years after close. 5 years, or until the hold ends, with a CERT-In report or a legal hold. |
| Abuse Report raw message | 1 year after the case closes. The parsed fields stay. |
| Abuse Report that was never attributed | 90 days |

Deletion jobs follow `clear_old_logs` (Log Settings), so all Central periods are visible and editable in one place. Atlas keeps its own periods in Abuse Settings.

Atlas records, the evidence snapshot, and the logs are in [Atlas abuse data](https://github.com/frappe/atlas/blob/develop/docs/abuse/data.md) and [Cargo abuse logs](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md).

### Legal hold

- `is_legal_hold` on the case keeps the case past its normal retention.
- Central sends the hold to Atlas in the abuse hold call. Atlas then keeps the evidence snapshot of a terminated VM past 30 days.
- A site under a legal hold gets HTTP 451 from the proxy.

### Deletion

Abuse Case and Abuse Exception link Team and Server. These links would block `Team.on_trash`. On team or server deletion, Central:

1. Copies the team name, the owner email, and the server name into plain fields.
2. Clears the links.

The owner email lets responders find a repeat offender who signs up again.

Central deletes Port 25 Requests with their team or server. They hold no evidence. A revoked request's cause stays on its Abuse Case.

Evidence holds no payloads. Addresses shown to customers are truncated to /24.

## Deploy order

Central deploys first. The full order is in [Atlas deploy order](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#deploy-order).

## Compared with AWS

| AWS | Frappe Cloud |
|---|---|
| Port 25 blocked, unblock by form | The same, with the trust tier as a gate. See [Email](#email). |
| Abuse report to the customer, with a deadline | Abuse Case with a deadline and the ladder. See [Report intake](#report-intake) and [Ladder](#ladder). |
| AWS Health abuse event, alternate security contact | Security notifications, the team security contact, and `security:view`. See [Customer messages](#customer-messages). |
| Shield Standard | Inbound DDoS protection and a notice to the customer. See [Inbound DDoS](#inbound-ddos). |

Differences from AWS: each notice holds the exact evidence. Self-quarantine is one click and keeps access through the WireGuard gateway. Breakers release automatically when the traffic stops.

## Sources

- AWS port 25: https://repost.aws/knowledge-center/ec2-port-25-throttle
- AWS abuse reports: https://repost.aws/articles/ARZVtmQf5CS_-UPgIJSCyr3A/securing-compromised-ec2-instances-implicated-in-abuse-reports
- AWS Health events: https://docs.aws.amazon.com/eventbridge/latest/ref/events-ref-health.html
- GuardDuty EC2 findings: https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_finding-types-ec2.html
- Hetzner lock reasons: https://docs.hetzner.com/robot/dedicated-server/troubleshooting/guideline-in-case-of-server-locking/
- Hetzner netscan remote trigger: https://forum.torproject.org/t/tor-relays-advisory-unauthenticated-remote-trigger-of-hetzners-netscan-detection/21295
- OVHcloud anti-hack: https://docs.ovhcloud.com/en/guides/bare-metal-cloud/dedicated-servers/anti-hack-dedicated-vps.md
- CERT-In sources: see [CERT-In](CERT_IN.md#sources).
