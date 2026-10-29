# Abuse protection

## Purpose

This document is the Central part of abuse protection in Frappe Cloud v2. It covers abuse that starts from, or targets, tenant resources in an Atlas region, and the messages to customers and operators about it.

Status: planned. Central does not implement this design yet. The DocType layouts in [Abuse layouts](ABUSE_LAYOUTS.md) need engineer approval before implementation. Change this document before you change the design.

Central owns detection and all policy: finding codes, thresholds, windows, profiles, exceptions, feeds, signals, cases, the ladder, reports, messages, CERT-In, and public IP history. Atlas exports metrics and logs, and applies or lifts a restriction when Central calls it. See the [Atlas abuse documentation](https://github.com/frappe/atlas/blob/develop/docs/abuse/index.md). Cargo owns the regional log bucket, its object layout, its keys, and the per-VM metric table in Datum. See [Cargo abuse logs](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md). CERT-In reporting is in [CERT-In](CERT_IN.md).

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
- Infrastructure VMs of tenant 0. Central does not know them, so detection skips them.

## Principles

1. Central detects and decides. Atlas exports metrics and logs, and applies or lifts a restriction when Central calls it. Atlas does not know teams, trust tiers, thresholds, or contacts.
2. Atlas never acts alone on abuse. Only an Atlas operator can apply an emergency restriction.
3. Restrictions live in a layer that the tenant API cannot write. Tenant firewall, route, and IPv4 changes cannot widen them.
4. Every restriction has a reason, an actor, a case, and an end condition. Terminate by an operator is the last step.
5. Restrict traffic, never compute. The abuse system never pauses or stops a VM.
6. Keep evidence before it is destroyed. Central snapshots the disk before it terminates a server with an open case or an active restriction. Never stop and start a VM to collect evidence.
7. Detection failure must not block customers. If Datum, Atlas, or Central is down, nothing new is applied, and automatic restrictions still end at `expires_at`.
8. Atlas stays backward compatible: optional fields and new endpoints only. Central deploys last. See [Deploy order](#deploy-order).

## Who does what

| Component | Responsible for | Acts alone |
|---|---|---|
| Metal (each host) | Per-VM counters exported to Datum, NAT and SNI logs uploaded to the log bucket, the `metal_abuse` chain, the `smtp_outbound` default block | No |
| Atlas app (each region) | VM Restriction, the restriction API, `is_port_25_allowed` on the VM, the `vm.restriction` event, the log write keys in Abuse Settings and in host and proxy config | Emergency restrictions by an Atlas operator only |
| HTTP proxy | Static rate limits, the abuse tombstone, the access log upload | No |
| Cargo | Log bucket and keys, the per-VM metric table in Datum and its Central read user, the phishing check on public buckets | No |
| Central | Detection, finding codes, thresholds, profiles, exceptions, feeds, Abuse Signal, Abuse Case, the policy engine, reports, all customer messages, the abuse dashboard, CERT-In, public IP history | Yes |
| Pilot | Nothing | Not applicable |

```text
Metal host          metrics      Datum (Cargo)       read user     Central
counters      ───────────────▶  vm_abuse_*, 30 d  ─────────────▶  detection, Abuse Signal
NAT, SNI logs ───────────────▶  Cargo log bucket  ─────────────▶  feed match, attribution
                                       ▲            read key       Abuse Case, policy engine
HTTP proxy: limits, tombstone, ────────┘                           messages, dashboard
            access log                                             Abuse Report, CERT-In
                                                                        │       ▲
metal_abuse  ◀─── host and VM config ─── Atlas app ◀── restriction ─────┘       │
                                         VM Restriction    API                  │
                                                  └───── vm.restriction ────────┘
```

## Roles and capabilities

| Name | Kind | Use |
|---|---|---|
| `Abuse Responder` | Desk role, planned. Not tied to a team. | Reads and writes Abuse Case, Abuse Report, Abuse Exception, Abuse Signal, Abuse Threshold, Abuse Feed, Public IP Assignment, and Port 25 Request. Works the abuse dashboard. |
| `security:view` | Team capability, planned | Reads the team's abuse cases and gets Security email. Owner and Admin roles get it by default. |
| `security:manage` | Team capability, planned | Responds to a case, requests a lift or an exception, applies and lifts self-quarantine, and requests a port 25 unblock. Implies `security:view`. Owner, Admin, and Developer roles get it by default. These are the roles that have `server:network`. |

Add `security:view` and `security:manage` to [Capabilities](../CAPABILITIES.md) and the fixtures in the implementation change. Developer gets `security:view` through the implication. Customers read cases only through the dashboard API, filtered by `security:view`. Each customer action on a case, a restriction, an exception, or a port 25 request needs `security:manage`.

## Detection

`central/abuse/detection.py` (planned) finds abuse. A scheduler job runs every minute for each Active region. It queries the per-VM metrics in the region's Datum through `central/integrations/datum.py` (planned), with a read-only ClickHouse user. The query URL and the user credentials are on the Region's Cargo connection. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#region-layout-change).

- The job compares each window with the [thresholds](#thresholds) of the region, after the [profile](#profiles) and any approved [exception](#abuse-exception).
- A match writes an [Abuse Signal](#signals).
- Central reads only metrics and log rows. It never reads the content of VM traffic.
- Central skips a VM that it does not know. These are the tenant 0 infrastructure VMs.
- If the Datum query of a region fails, or its newest sample is older than 5 min, Central alerts Raven `#abuse`. Central applies nothing new in that region until the query works again.

### Metrics

Metal exports per-VM counters to Datum at the metald telemetry interval, 30 s by default. Each series has the label `virtual_machine`, the Atlas VM name. Central maps it to a server through `Virtual Machine.atlas_vm_id`. Datum keeps `vm_abuse_*` series for 30 days. See [Atlas counters](https://github.com/frappe/atlas/blob/develop/docs/abuse/metrics.md#counters) and [Cargo per-VM metrics](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md#per-vm-metrics).

Central uses these series:

| Series | Use |
|---|---|
| `vm_abuse_transmit_packets_total`, `vm_abuse_transmit_bytes_total` | Outbound floods and volume. Labels `scope` (public or mesh) and `protocol`. |
| `vm_abuse_receive_packets_total`, `vm_abuse_receive_bytes_total` | Answer ratios and inbound floods. Same labels. |
| `vm_abuse_tcp_initiated_total`, `vm_abuse_tcp_answered_total` | SYN floods and scan answer ratios |
| `vm_abuse_udp_first_packets_total` | UDP to new destinations |
| `vm_abuse_destinations` | Gauge: distinct public destinations in the window. Labels `port_class` (a class, or `all`) and `window` (`60s` or `10m`). |
| `vm_abuse_ports_per_destination_max` | Gauge: the highest number of distinct ports to one public address in the last 60 s |
| `vm_abuse_flows_per_destination_max` | Gauge: the highest number of new flows to one public address in the last 10 min. Label `port_class`. |
| `vm_abuse_unanswered_pairs` | Gauge: unanswered address and port pairs in the last 1 h |
| `vm_abuse_smtp_blocked_total` | Port 25 attempts that `smtp_outbound` blocked |
| `vm_abuse_stratum_flows_total` | New flows with a stratum match in the first payload bytes |
| `vm_abuse_amplification_bytes_total` | Public UDP bytes of the `amplification` class. Labels `direction` and `port`. `transmit` counts bytes from an amplification source port. `receive` counts bytes to an amplification destination port. |

The definitions of the series and their labels are in [Atlas counters](https://github.com/frappe/atlas/blob/develop/docs/abuse/metrics.md#counters).

Central computes rates from counter differences. A counter that goes down is a metald restart. Central treats it as a gap, not as a rate.

Port classes (`auth`, `smtp`, `submission`, `amplification`, `mining`) are a fixed list in metald. See [Atlas port classes](https://github.com/frappe/atlas/blob/develop/docs/abuse/metrics.md#port-classes). Central keeps a copy of the list in code, and changes it together with metald. Central uses it to turn a class into explicit ports for `port_block`.

### Finding codes

A finding code uses the GuardDuty style `<threat>:<resource>/<name>`. A finding never names a reporter. Customer evidence holds counts, ports, times, and destination prefixes truncated to /24.

| Finding code | Signal | Source |
|---|---|---|
| `DoS:VM/OutboundFlood` | Public pps or bps above the threshold | Datum |
| `DoS:VM/SynFlood` | Initiated SYN to few destinations, few answered | Datum |
| `Recon:VM/Portscan` | Fan-out with a low answer ratio | Datum |
| `UnauthorizedAccess:VM/BruteForce` | Auth ports to many addresses, or many connections to one | Datum |
| `Smtp:VM/BlockedPort25` | A few blocked port 25 attempts | Datum |
| `Spam:VM/Smtp` | Many port 25 attempts, a submission spray, or our address on a DNSBL or in SNDS | Datum, feed |
| `Reflector:VM/<protocol>` | Amplification ratio, or a Shadowserver report | Datum, feed |
| `CryptoCurrency:VM/PoolConnection` | Pool address from the feed in the NAT log, or a stratum match | NAT log, Datum |
| `CryptoCurrency:VM/PoolName` | Pool name in the SNI log | SNI log |
| `Backdoor:VM/C2Activity` | Flows to Spamhaus DROP or abuse.ch Feodo addresses | NAT log |
| `Phishing:Site/LookalikeDomain` | A site hostname with a brand term on a young team | Site Domain |
| `Proxy:VM/Tor` | Connections to Tor relays from the public consensus | NAT log |
| `Phishing:Site/Reported` | Site hostname on Safe Browsing, OpenPhish, or URLhaus, or in a report | Feed, report |
| `Phishing:Bucket/Reported` | Public bucket hostname on a phishing feed | Cargo |
| `Content:Site/Illegal` | Report only | Report |
| `DoS:VM/InboundFlood` | Received pps or bps on a VM above the threshold | Datum |

The [policy engine](#policy-engine) decides the next step for each finding.

### Threshold rules

1. Every rule has a volume floor and a shape condition: answer ratio, packet size, fan-out, or protocol.
2. Rules count public traffic only. Mesh traffic never counts.
3. Limits are absolute. They do not change with the VM size.
4. A rule needs a series in [Metrics](#metrics). A rule whose series Metal does not export stays Off.

### Windows

Every window is 1 min or longer. The rules that used 30 s now use 2 min.

| Window | Use |
|---|---|
| 1 min | Volumetric flood, horizontal and vertical scan, reflector |
| 2 min | UDP, small-packet, ICMP, and SYN floods, inbound flood |
| 10 min | Brute force, SMTP, mining stratum |
| 1 h | Slow scan, C2 |

Reaction time is the window, plus up to 30 s until the next sample, plus up to 1 min until the next scheduler run. For the flood and scan rules, with 1 min and 2 min windows, this is about 3 min (2.5 min to 3.5 min) from the start of abuse to a restriction. No automatic limit exists before that. A VM can flood or scan for these minutes. This is an accepted trade-off: Atlas keeps no detection state, and Central makes every decision.

### Thresholds

An Abuse Threshold holds the trigger values of one finding code in one region. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-threshold).

- `mode` is Off, Shadow, or Active. Shadow writes signals with `is_shadow` and opens no case. Active also sends the signal to the policy engine.
- An operator changes a value or a mode in Desk, with no deploy.
- These are starting values. They ship as fixtures, not as JSON defaults, so a region can use other values. No value is Active until [calibration](#calibration) confirms it.
- The "Reads" column names the [series](#metrics) or the source of each rule. Rates and ratios use the `scope="public"` series. A 1 min count of destinations reads `window="60s"`. A 10 min count reads `window="10m"`.

Outbound to public destinations:

| Rule | Finding code | Trigger | Reads |
|---|---|---|---|
| UDP flood | `DoS:VM/OutboundFlood` | UDP above 20k pps for 2 min, and received below 10% of sent or fewer than 8 destinations | `vm_abuse_transmit_packets_total` and `vm_abuse_receive_packets_total` with `protocol="udp"`, `vm_abuse_destinations{port_class="all",window="60s"}` |
| Small-packet flood | `DoS:VM/OutboundFlood` | Above 20k pps for 2 min, average packet below 200 bytes | `vm_abuse_transmit_packets_total`, `vm_abuse_transmit_bytes_total` |
| Volumetric | `DoS:VM/OutboundFlood` | Above 1 Gbit/s for 1 min, received below 5% of sent | `vm_abuse_transmit_bytes_total`, `vm_abuse_receive_bytes_total` |
| ICMP flood | `DoS:VM/OutboundFlood` | Above 1k pps for 2 min | `vm_abuse_transmit_packets_total{protocol="icmp"}` |
| SYN flood | `DoS:VM/SynFlood` | Initiated SYN above 2k/s for 2 min, answered below 10% | `vm_abuse_tcp_initiated_total`, `vm_abuse_tcp_answered_total` |
| Horizontal scan | `Recon:VM/Portscan` | 256 or more addresses in one port class in 1 min, below 25% answered | `vm_abuse_destinations{window="60s"}` for each port class, `vm_abuse_tcp_initiated_total`, `vm_abuse_tcp_answered_total` |
| Vertical scan | `Recon:VM/Portscan` | 512 or more ports on one address in 1 min, below 25% answered | `vm_abuse_ports_per_destination_max`, `vm_abuse_tcp_initiated_total`, `vm_abuse_tcp_answered_total` |
| Slow scan | `Recon:VM/Portscan` | 2,000 or more unanswered address and port pairs in 1 h. Low severity. | `vm_abuse_unanswered_pairs` |
| Brute force | `UnauthorizedAccess:VM/BruteForce` | The `auth` class to 64 or more addresses in 10 min, or 300 or more new flows to one address in 10 min | `vm_abuse_destinations{port_class="auth",window="10m"}`, `vm_abuse_flows_per_destination_max{port_class="auth"}` |
| Reflector | `Reflector:VM/<protocol>` | Amplification source port, bytes out above 10 times bytes in, above 10 Mbit/s for 1 min | `vm_abuse_amplification_bytes_total`, `transmit` against `receive` for each `port`. The `port` gives the protocol, for example 53 is DNS. |

SMTP:

| Rule | Trigger | Result | Reads |
|---|---|---|---|
| Port 25 misconfiguration | 1 to 19 blocked attempts in 10 min | `Smtp:VM/BlockedPort25`, Low | `vm_abuse_smtp_blocked_total` |
| Port 25 spam | 500 or more blocked attempts in 10 min, or 50 or more destinations | `Spam:VM/Smtp`, Medium | `vm_abuse_smtp_blocked_total`, `vm_abuse_destinations{port_class="smtp",window="10m"}` |
| Submission spray | The `submission` class to 20 or more addresses, or 300 or more new flows to one address, in 10 min | `Spam:VM/Smtp`, Medium | `vm_abuse_destinations{port_class="submission",window="10m"}`, `vm_abuse_flows_per_destination_max{port_class="submission"}` |
| DNSBL listing | A listing of the public address of a server | `Spam:VM/Smtp` from the feed. See [DNSBL response](#dnsbl-response). | DNSBL feeds |

Other rules:

| Rule | Trigger | Reads |
|---|---|---|
| Mining pool, feed | 1 match of a pool address in the NAT log, or of a pool name in the SNI log | NAT log, SNI log |
| Mining pool, stratum | 1 or more stratum flows in 10 min | `vm_abuse_stratum_flows_total` |
| C2 | 1 flow to abuse.ch Feodo, or 3 flows in 1 h to Spamhaus DROP | NAT log |
| Lookalike domain | A site hostname with a brand term, on a team younger than 30 days. `Phishing:Site/LookalikeDomain`, Low. An operator reviews it. See [Phishing sites](#phishing-sites). | Site Domain, team age |
| Inbound flood | Above 20k pps or 1 Gbit/s received for 2 min. Central applies `ingress_throttle` and sends `security_inbound_attack`. See [Inbound DDoS](#inbound-ddos). | `vm_abuse_receive_packets_total`, `vm_abuse_receive_bytes_total` |

The HTTP proxy has static limits for each client address and site: `limit_req` 100 requests a second with a burst of 500, and `limit_conn` 200. Central does not change them. See [Atlas HTTP proxy](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md#http-proxy).

### Profiles

Central picks a profile for each server on each detection run, from team data. The profile stays in Central. Atlas does not get it.

| Profile | For | Effect |
|---|---|---|
| `strict` | Free trial servers, and teams that never paid | Volume triggers at `strict_multiplier` (start with 0.5) |
| `standard` | All other servers | The values in [Thresholds](#thresholds) |
| `relaxed` | Trust tier 3 (Advance) or higher, and no case in 90 days | Volume triggers at `relaxed_multiplier` (start with 2) |

When rules overlap, Central uses the first match:

1. A free trial server is `strict`.
2. A team at trust tier 3 (Advance) or higher is `relaxed`. This includes teams without payments that have a manual override.
3. A team that never paid is `strict`.
4. All other servers are `standard`.

- A multiplier changes volume values: rates, counts of addresses, and counts of attempts. It does not change ratios, feed matches, or stratum matches.
- The multipliers are in Central Settings. See [Settings](#settings).
- There is no profile for infrastructure VMs. Central skips VMs that it does not know.

### Exceptions

An approved [Abuse Exception](#abuse-exception) changes one finding code on one server until it expires. Detection reads it on each run. Central sends nothing to Atlas.

### Feeds

An Abuse Feed holds one external list. Central fetches each enabled feed on its own schedule. A feed match is an Abuse Signal with source Feed. A feed is not an abuse report, so Central sends no reply. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-feed).

| Feed | Use |
|---|---|
| Mining pools | Pool addresses and names |
| Spamhaus DROP, abuse.ch Feodo | C2 addresses |
| Tor consensus | Tor relay addresses |
| Safe Browsing, OpenPhish, URLhaus | Phishing and malware hostnames |
| DNSBLs: Spamhaus ZEN, Barracuda, and others | Listings of our public addresses |
| Microsoft SNDS | Spam trap hits and complaints for our address ranges |
| Shadowserver | Reports for the region's prefixes, through its API |

Central matches feeds in three ways:

- Logs. Metal uploads one NAT log object and one SNI log object for each host every 5 min. After each upload, Central reads the new objects from the Cargo log bucket with the read key, and matches the destination addresses and server names against the feeds. See [Cargo object layout](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md#object-layout), [Atlas NAT log](https://github.com/frappe/atlas/blob/develop/docs/abuse/metrics.md#nat-log), and [Atlas SNI log](https://github.com/frappe/atlas/blob/develop/docs/abuse/metrics.md#sni-log).
- Site hostnames. Central checks each Site Domain against the phishing feeds when the domain is added, and every day after.
- Public addresses. Central checks the `public_ipv4` and `public_ipv6` of each server that is not Terminated against the DNSBLs every hour.

Limitation: Central knows only the addresses of its own servers. A listed address can go to a new server. If the server got the address less than 7 days before Central first sees the listing, Central posts the listing to Raven `#abuse` and opens no case for the new team. An operator gets the address delisted.

### Signals

An Abuse Signal is one match of one finding code on one server, or on one bucket or site, in one window. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-signal).

- Fields: team, server, finding code, severity, source, `window_start`, `window_end`, values, `is_shadow`, and `is_false_positive`.
- Values hold counts, rates, top destination ports, and destination prefixes truncated to /24.
- A match that continues an open signal of the same server and finding code moves its `window_end`. A gap of more than one window starts a new signal.
- A signal from an Active threshold goes to the policy engine. The policy engine finds or opens the case for (team, server, finding code), and links the signal to it.
- A shadow signal opens no case.
- Sources: Detection, Feed, Cargo, Report, or Operator.

### Mining detection

The AUP forbids mining on every server. CPU use alone is never evidence. Central finds mining from:

- `vm_abuse_stratum_flows_total`. Metal reads only the first payload bytes of new flows to non-standard ports for this match.
- Matches of pool addresses in the NAT log, and of pool names in the SNI log, against the mining pool feed.

The outcomes are in [Mining](#mining).

### Calibration

1. Baseline. Until per-VM metrics are in Datum, an operator runs the Atlas script [atlas-abuse-baseline.py](https://github.com/frappe/atlas/blob/develop/scripts/atlas-abuse-baseline.py) on every Metal host from 2 to 7 November 2026, so that the samples include the October month end. Agents do not run it. Its data includes mesh traffic and counts a SYN-ACK as a SYN, so it gives upper bounds only.
2. Shadow. Every Abuse Threshold `mode` is Shadow for at least 4 weeks, with a month end. Signals get `is_shadow`. Central opens no case for them.
3. Red team in staging, from a test tenant. Each row must give a signal in time:

   | Tool | Rule | Signal within |
   |---|---|---|
   | masscan at 100, 1k, and 10k pps | Horizontal scan | 3 min |
   | nmap `-T3` and `-T4`, top 1000 ports | Vertical scan | 3 min |
   | hping3 `--flood`, SYN and UDP | SYN flood, UDP flood | 4 min |
   | hydra against 100 SSH hosts in a test range | Brute force | 12 min |
   | iperf3 UDP at 2 Gbit/s to a silent sink | Volumetric | 3 min |
   | xmrig to a test stratum server | Mining, stratum | 12 min |
   | swaks loop to 100 MX hosts on port 25 | Port 25 spam | 12 min |

   These must stay silent: a bench build (yarn, pip, git), `apt upgrade`, a 50 GB backup to S3, a month-end run of 10k emails, a 500 Mbit/s WireGuard VPN, and a crawler on 1k sites.
4. Active. Switch one finding code at a time, when false positives are below 1 for each 1,000 VM-days and every red-team row gives a signal.

After that, responders mark disputed signals `is_false_positive`. The daily digest shows false positives for each finding code. Operators tune each region in its Abuse Thresholds.

## Abuse Case

An Abuse Case is the record of one abuse problem on one server. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-case).

- Central keeps one open case for each (team, server, finding code), or for each (team, bucket, finding code).
- The name is `AC-.#####`. It is the reference in mail subjects, for example `[AC-00192]`.
- A case links its Abuse Signals. They come from detection, feeds, Cargo reports, Abuse Reports, or an operator.
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
| 0 | Signal | Central detection | Not applicable |
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
| Defaults | The `smtp_outbound` default block | Not a ladder step and not history |

### Lifts

Each customer action below needs `security:manage`.

- Self-lift: once for each case, for level 2 or 3, after the customer writes what they fixed.
- Automatic return: the same finding category on the team within 7 days of a self-lift puts the restriction back, with no new deadline. After that, only an operator lifts it.
- Lift request: for any other restriction, the customer asks on the case page. The response kind is `Lift Requested`. A responder decides.
- Self-quarantine: the customer can apply `quarantine` from the Security tab. See [Self-quarantine](#self-quarantine).

### New servers

While a team has an open case at level 3 or 4, every new server starts with the same restriction. Central sends it in the optional `restrictions` field of the Atlas VM create request. Each inherited restriction has its own `idempotency_key`, the name of a new Resource Action, and the `case_reference` of the case. The restriction ends with the case. Restrictions are VM config, so they move with a VM on migration.

### Restrictions

Central applies and lifts restrictions through the Atlas restriction API. See [Apply a restriction](#apply-a-restriction).

- Kinds: `egress_throttle`, `ingress_throttle`, `port_block`, `quarantine`, and `isolate`.
- `port_block` takes explicit ports with their protocol. Central resolves port classes to ports from its copy of the [Atlas port classes](https://github.com/frappe/atlas/blob/develop/docs/abuse/metrics.md#port-classes). Atlas does not know port classes.
- States: `Pending`, `Applied`, `Lifted`, and `Failed`. See [Atlas restriction states](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md#restriction-states).
- On `Failed`, Central sets the case to Escalated and posts to Raven `#abuse`. Central does not apply the restriction again with a new key.

Who changes restrictions:

- Normal: the policy engine or an operator in Central calls the restriction API. Central records a Resource Action with action `restrict` (a new action) and a system actor, and links the case.
- Emergency: an Atlas operator creates a VM Restriction in Atlas Desk. Atlas sends `vm.restriction` with `applied_by_user` and no `idempotency_key`. Central links the restriction to an open case, or opens a case.
- Expiry: Atlas ends a restriction at `expires_at`. Central records the end from `vm.restriction`, with `lifted_by` set to `Expiry`.

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

- An immediate level 2 restriction from detection has `expires_at` 24 h after it is applied. So a failure in detection or in Central never leaves it in place for long.
- While the match continues, the open signal moves its `window_end`. When less than 12 h of the restriction remain, Central extends it with a new `expires_at`. See [Calls to Atlas](#calls-to-atlas).
- An extension never resets the deadline or the ladder level.
- Example: a scan from a trial that never paid is isolated. The same scan from a Tier 3 team that paid for 12 months gets a `port_block`, a notice, and 24 h.
- At a deadline, the policy engine takes the next ladder step and sends `abuse_restriction_applied`.
- Abuse history lowers the trust tier. A resolved case with a fix restores the tier after 90 days.

The finding codes and their meaning are in [Finding codes](#finding-codes).

## Abuse Exception

An Abuse Exception lets a team change one detection rule on one server for a fixed period. Example: an authorized penetration test. It is team-scoped. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-exception).

- A member with `security:manage` requests it on the server's Security tab. A responder approves or rejects it.
- Fields: team, server, finding code, effect (a multiplier, or disabled), reason, expiry, and approver.
- The expiry is at most 90 days after the start.
- Detection applies an approved exception until it expires or a responder revokes it. The exception stays in Central. Atlas gets nothing.
- The controller refuses the `smtp_outbound` default block. Port 25 has its own flow. See [Email](#email).

## Controls

Central never reads the content of a VM's traffic. Metal reads only the TLS server name and, for mining, the first payload bytes of new flows to non-standard ports. The AUP and the privacy policy must say so before Metal turns on the SNI log.

### Email

Port 25 is blocked for every VM by the `smtp_outbound` default block. The submission ports 465 and 587 stay open. See [Atlas metal_abuse chain](https://github.com/frappe/atlas/blob/develop/docs/abuse/enforcement.md#metal_abuse-chain).

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
- For `Spam:VM/Smtp` with a DNSBL listing, Central applies `port_block` on the ports of the `smtp` and `submission` classes. An operator gets the address delisted.
- DNSBL notices that arrive by email become Abuse Reports. See [Report intake](#report-intake).
- Central checks the public addresses of its servers against DNSBLs. A listing on an address that a server got recently opens no case. See [Feeds](#feeds).

### Phishing sites

- Central suspends a site with `proxy.suspend_site(name, reason_code)` in `central/integrations/proxy.py`. The proxy serves a branded suspended page with HTTP 403 for abuse, or HTTP 451 for a legal hold, and a link to the abuse page.
- Central suspends automatically only when the source is a Trusted feed or reporter, or when another signal corroborates it. Otherwise an operator checks first.
- Only an operator lifts a site suspension.
- Central checks site hostnames against phishing feeds. A match is an Abuse Signal with `Phishing:Site/Reported`. See [Feeds](#feeds).
- Central gives a score to hostnames with brand terms on teams younger than 30 days. A match is an Abuse Signal with `Phishing:Site/LookalikeDomain`, Low severity, for an operator to review. See [Thresholds](#thresholds).

### Public buckets

This flow applies only after Cargo offers public buckets. Cargo has no public buckets today.

- Cargo checks the hostname of each public bucket against phishing feeds. See [Cargo public buckets](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md#public-buckets).
- Cargo sends a match to Central in its `storage` report. See [Reports from Cargo](#reports-from-cargo).
- Central opens a case for the team that owns the bucket.
- Central can suspend the bucket with `suspend_bucket`, and lift the suspension with `unsuspend_bucket`. See [Calls to Cargo](#calls-to-cargo).

### Mining

The AUP forbids mining on every server, trial or paid. CPU use alone is never evidence. Detection is in [Mining detection](#mining-detection).

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

- On an inbound flood, Central applies `ingress_throttle` to the VM. See [Thresholds](#thresholds).
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

A shared NAT address names no single server. For it, Central reads the NAT log objects in the Cargo log bucket. See [Atlas NAT log](https://github.com/frappe/atlas/blob/develop/docs/abuse/metrics.md#nat-log).

## Report intake

Abuse reports live only in Central.

### Channels

| Channel | Path |
|---|---|
| Email | `abuse_email`, read by a Frappe incoming Email Account. The same address is the IRT and `abuse-c` contact in APNIC WHOIS for our prefixes. |
| Web form | Guest page `/abuse`: category, address or hostname, port, time with timezone, description, and evidence upload. hCaptcha, a rate limit for each IP, and an upload size limit. |
| Feeds | Central fetches feeds. Matches are signals with source Feed, not reports. Central sends no reply. See [Feeds](#feeds). |
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
   - Shared NAT address: the NAT log objects in the Cargo log bucket for the time, with the read key. Method NAT Log.
   - Proxy address: the proxy access log objects in the Cargo log bucket. Method Proxy Route.
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
| `strict_multiplier`, `relaxed_multiplier` | Profile multipliers. See [Profiles](#profiles). Start with 0.5 and 2. |
| `cert_in_contact_*` | Name, designation, organisation, address, email, mobile, phone, and fax (optional). CERT-In Annexure II. |
| `cert_in_incident_email` | The address that gets CERT-In reports |

When a field is empty:

- Central does not guess and has no fallback.
- The abuse dashboard shows a red banner that names the field. The readiness checks fail, as in `central/billing/platform/readiness.py`.
- Central does not send a message that needs the field. It writes an Error Log and sets `has_operator_notification_failure` on the case. The case status does not change.
- Detection does not run until both profile multipliers are set.
- "Build report" refuses until the CERT-In contact fields are set.
- Customer notices still go out.

The Datum and log bucket credentials of each region are on the Region. See [Reads from Datum](#reads-from-datum) and [Reads from the log bucket](#reads-from-the-log-bucket).

### Channels

| Channel | Gets |
|---|---|
| Email to `abuse_email` | Every Critical case, copies of reporter acknowledgements, CERT-In clock alerts |
| Raven `#abuse-p1` (pages on call) | Critical findings, region-level floods, illegal content, unconfirmed cases past their SLA, CERT-In clocks with 2 h left |
| Raven `#abuse` | Cases that need a person (dispute, port 25 review, failed attribution, deadline reached on a paid team, `Notification Failed`, a `Failed` restriction), DNSBL listings with no case, and detection failures in a region |
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
│ Cases opened vs closed   │ Detection lag by region   │ False positives (7 d): 1     │
├──────────────────────────┴───────────────────────────┴──────────────────────────────┤
│ Unattributed reports 4   Port 25 requests 2   Disputes 1   Restrictions > 14 days 0 │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

Case view:

- Evidence pack: the signal timeline, per-VM graphs from Datum for up to 30 days, and NAT, SNI, and proxy log lines from the Cargo log bucket. See [Reads from Datum](#reads-from-datum) and [Reads from the log bucket](#reads-from-the-log-bucket).
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

- `track_changes` is on for Abuse Case, Abuse Exception, Abuse Signal, Abuse Threshold, and Port 25 Request. Atlas VM Restriction rows and Central Resource Actions are the audit record of who restricted a VM and why.
- The Central investigator agent gets read tools for abuse cases.
- Central alerts `#abuse` when the detection job of a region fails or reads stale data. See [Detection](#detection).

## Interfaces

All Atlas changes are optional fields or new endpoints. There is no new API version. Central calls other planes only from `central/integrations/`. The Atlas side of this contract is in [Atlas abuse contract](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md).

### Events from Atlas

Atlas sends one new event, `vm.restriction`, through the signed webhook path to `central.api.state_delivery.receive`. See [Inbound webhooks](WEBHOOKS.md) for the signature, headers, and retries. The event fields are in [Atlas events to Central](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#events-to-central).

| Field | Value |
|---|---|
| `restriction_id` | The name of the VM Restriction. Central matches it to `atlas_restriction_id`. |
| `virtual_machine` | The Atlas VM ID |
| `kind` | The restriction kind |
| `status` | `Pending`, `Applied`, `Lifted`, or `Failed` |
| `idempotency_key` | Optional. The Resource Action name from the apply request or the VM create request. |
| `case_reference` | Optional. The Abuse Case name from the request. |
| `expires_at` | Optional. The end time of the restriction. |
| `lifted_by` | Optional. `Central`, `Expiry`, or `Atlas user`. Set when the status is `Lifted`. |
| `applied_by_user` | Optional. The Atlas operator of an emergency restriction. |

- Central matches the event to an Abuse Case Restriction row by `restriction_id`.
- When Central does not know the name, it matches by `idempotency_key`. This occurs for an inherited restriction, and after a lost apply response. Central then stores the name in `atlas_restriction_id`.
- An event with `applied_by_user` and no `idempotency_key` is an emergency restriction. It links to an open case or opens one.
- Central sets `ended_by` on the row from `lifted_by`.
- `state_delivery._decide` and `apply_atlas_report` accept the event.
- A repeated event with the same ID updates the same row. It never adds a second row.
- Central's repair scan reads `restrictions` from the Atlas `GET` VM response, and applies the same update for each missed `vm.restriction` event. See [Calls to Atlas](#calls-to-atlas).
- Today Central ignores unknown events with HTTP 200, so an older Central ignores the event.

### Calls to Atlas

Central calls these through `central/integrations/atlas.py`. Each one is `central_only`. See [Atlas restriction API](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#restriction-api).

| Call | Use |
|---|---|
| `PUT /api/atlas/virtual-machines/<id>/restrictions` | Apply a restriction. Idempotent by `idempotency_key`. See [Apply a restriction](#apply-a-restriction). |
| `PATCH /api/atlas/virtual-machines/<id>/restrictions/<name>` | Extend a level 2 restriction with a new `expires_at`, while the match continues and less than 12 h remain. See [Policy engine](#policy-engine). |
| `DELETE /api/atlas/virtual-machines/<id>/restrictions/<name>` | Lift a restriction by its `name`. Idempotent. |

Changed requests, with optional fields:

| Request | Field |
|---|---|
| VM create | `restrictions` (inherited, each with `idempotency_key` and `case_reference`, see [New servers](#new-servers)) |
| VM update | `is_port_25_allowed` |
| `GET` VM response | `restrictions`. Central's repair scan reads it, and reconciles missed `vm.restriction` events. See [Events from Atlas](#events-from-atlas). |

Before Central terminates a server with an open case or an active restriction, it takes a snapshot of the disk through the existing Atlas snapshot action. The snapshot is a VM Snapshot with `is_abuse_evidence` set. Central keeps it for 30 days, or longer on a legal hold. The customer dashboard never lists it, and the customer cannot delete it. Only `Abuse Responder` and System Manager read it. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#vm-snapshot-layout-change).

#### Apply a restriction

Central sends:

| Field | Value |
|---|---|
| `idempotency_key` | The name of the Resource Action for the restriction |
| `case_reference` | The Abuse Case name, for example `AC-00192` |
| `kind` | `egress_throttle`, `ingress_throttle`, `port_block`, `quarantine`, or `isolate` |
| `parameters` | For `port_block`: `ports`, each with a port and a protocol. For a throttle: the limits. |
| `expires_at` | Optional. Atlas ends the restriction at this time. |

```json
{
	"idempotency_key": "8f3k2m1q9a",
	"case_reference": "AC-00192",
	"kind": "port_block",
	"parameters": {"ports": [{"port": 25, "protocol": "tcp"}, {"port": 465, "protocol": "tcp"}, {"port": 587, "protocol": "tcp"}]},
	"expires_at": "2026-10-30T10:14:00Z"
}
```

Atlas returns the restriction `name`. Central stores it in `atlas_restriction_id` and uses it to lift the restriction. A repeat with the same `idempotency_key` returns the same name. A lost response leaves the Resource Action uncertain, and Central does not send a second apply with a new key.

### Reads from Datum

`central/integrations/datum.py` (planned) queries the per-VM `vm_abuse_*` table of a region's Datum. It uses a read-only ClickHouse user that Cargo makes for Central. An operator copies the query URL, the user, and the password into the Region. See [Cargo per-VM metrics](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md#per-vm-metrics) and [Atlas telemetry](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#telemetry).

- Detection reads the last windows every minute. See [Detection](#detection).
- The evidence pack reads up to 30 days for one VM.
- Central keeps the queries narrow: one region, a time range, and the `vm_abuse_*` table only.

### Reads from the log bucket

Central reads the NAT, SNI, and proxy access log objects in the region's Cargo log bucket with the read key. An operator copies the endpoint, the bucket name, and the read key from Cargo into the Region. Atlas has no read key. See [Cargo keys](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md#keys) and [Atlas log upload](https://github.com/frappe/atlas/blob/develop/docs/abuse/contract.md#log-upload).

- Feed matching reads each new 5 min object once. See [Feeds](#feeds).
- Report attribution and the evidence pack read the objects around one time.
- Central reads objects only after their upload, so the newest 5 min are not visible yet.
- Central never copies log objects out of the region. SNI rows can be personal data.

### Calls to the proxy

Through `central/integrations/proxy.py`:

- `suspend_site(name, reason_code)`: sets the abuse tombstone on a site route.

### Calls to Cargo

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

- Central finds the team of the bucket, and adds or updates an Abuse Signal with source Cargo by `cargo_signal_id`. It finds or opens the case for (team, bucket, finding code) and links the signal.
- Central writes an Error Log for a signal on a bucket that it does not know. It opens no case for it.
- Today Central ignores unknown fields in a Cargo report. So Cargo can send the list before Central reads it.

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

Datum keeps the per-VM metrics for 30 days. The log bucket keeps the logs for 180 days. See [Cargo abuse logs](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md). Atlas keeps VM Restriction for its own period. See [Atlas retention](https://github.com/frappe/atlas/blob/develop/docs/abuse/data.md#retention).

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

1. Cargo: the log bucket and its keys, the per-VM Datum table with its 30-day TTL, and the Central read user.
2. Atlas app: the restriction API, `restriction_status` in host sync, and the write keys in host and proxy config.
3. Metal: the counters and their export, the `metal_abuse` chain with `smtp_outbound`, and the log upload.
4. HTTP proxy: the tombstone and the log upload.
5. Central: detection with every Abuse Threshold in Shadow, then cases and restrictions.

All Atlas changes are optional fields: an old Central ignores them. Public IP history has no dependency, so Central can ship it before step 1.

## Compared with AWS

| AWS | Frappe Cloud |
|---|---|
| Port 25 blocked, unblock by form | The same, with the trust tier as a gate. See [Email](#email). |
| Abuse report to the customer, with a deadline | Abuse Case with a deadline and the ladder. See [Report intake](#report-intake) and [Ladder](#ladder). |
| AWS Health abuse event, alternate security contact | Security notifications, the team security contact, and `security:view`. See [Customer messages](#customer-messages). |
| Shield Standard | Inbound DDoS protection and a notice to the customer. See [Inbound DDoS](#inbound-ddos). |

Differences from AWS: each notice holds the exact evidence. Self-quarantine is one click and keeps access through the WireGuard gateway. Automatic restrictions from detection expire by themselves.

## Sources

- AWS port 25: https://repost.aws/knowledge-center/ec2-port-25-throttle
- AWS abuse reports: https://repost.aws/articles/ARZVtmQf5CS_-UPgIJSCyr3A/securing-compromised-ec2-instances-implicated-in-abuse-reports
- AWS Health events: https://docs.aws.amazon.com/eventbridge/latest/ref/events-ref-health.html
- GuardDuty EC2 findings: https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_finding-types-ec2.html
- Hetzner lock reasons: https://docs.hetzner.com/robot/dedicated-server/troubleshooting/guideline-in-case-of-server-locking/
- Hetzner netscan remote trigger: https://forum.torproject.org/t/tor-relays-advisory-unauthenticated-remote-trigger-of-hetzners-netscan-detection/21295
- OVHcloud anti-hack: https://docs.ovhcloud.com/en/guides/bare-metal-cloud/dedicated-servers/anti-hack-dedicated-vps.md
- CERT-In sources: see [CERT-In](CERT_IN.md#sources).
