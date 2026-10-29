# Abuse layouts

## Purpose

This document holds the mockups for the new Central DocTypes and layout changes of [Abuse protection](ABUSE.md).

Status: awaiting engineer approval. Do not write DocType JSON before an engineer approves these layouts. Follow the Desk rules in [the repository guide](../CLAUDE.md#desk-and-operations).

The Atlas layouts (VM Restriction and the Virtual Machine change) are in [Atlas abuse layouts](https://github.com/frappe/atlas/blob/develop/docs/abuse/layouts.md).

Notation:

- `[Section]` is a section, `{Tab}` is a tab, and `|` separates columns.
- Each field shows the label, the fieldname, and the type.
- RO means read only.
- `Link VM` is a Link to Virtual Machine.

## Roles

- New Desk role `Abuse Responder`: reads and writes every DocType below.
- `System Manager` as usual.
- Customers read cases only through the dashboard API, filtered by `security:view`. Customer actions need `security:manage`.

## Abuse Case

Team-scoped: an indexed `team` field, `abuse_case_query_conditions`, and `abuse_case_has_permission`. Naming: `AC-.#####`, the reference in mail subjects. `track_changes` on.

```text
┌ Abuse Case AC-00192 ──────────────────────────────────────────────────────────────────────┐
│ {Case}                                                                                    │
│ [Case]                                                                                    │
│ Team              team              Link Team RO     │ Status           status   Select  │
│ Server            server            Link VM RO       │   Open / Awaiting Customer /      │
│ Bucket            bucket            Data RO          │   Notification Failed /           │
│ Region            region            Link Region RO   │   Restricted / Escalated /        │
│                                                      │   Resolved / Closed               │
│ Finding Code      finding_code      Data RO          │ Severity         severity  Select │
│ Category          category          Select RO        │ Ladder Level     ladder_level Int │
│   Spam / Phishing / Malware / Scanning / Brute       │                                   │
│   Force / DoS / Mining / Copyright / Illegal         │                                   │
│   Content / Other                                    │                                   │
│                                                                                           │
│ [Deadline]                                                                                │
│ Notice Delivered  notice_delivered_at  Datetime RO   │ Self-Lift Used   is_self_lift_used│
│ Response Due      response_due_at      Datetime RO   │                  Check RO         │
│                                                      │ Delivered By Other Channel        │
│                                                      │  is_delivered_by_other_channel Chk│
│ [Customer]                                                                                │
│ Customer Response customer_response    Text RO       │ Responded At  responded_at  DT RO │
│ Response Kind     customer_response_kind Select RO   │                                   │
│   Acknowledged / Fixed / Lift Requested / Disputed   │                                   │
│                                                                                           │
│ [Signals]                                                                                 │
│ Signals           signals           Table RO  Abuse Case Signal (links Abuse Signal)      │
│ [Restrictions]                                                                            │
│ Restrictions      restrictions      Table RO  Abuse Case Restriction                      │
│                                                                                           │
│ {Notifications}                                                                           │
│ Operator Notification Failed  has_operator_notification_failure  Check RO                 │
│ Notifications     notifications     Table RO  Abuse Case Notification                     │
│                                                                                           │
│ {CERT-In}                                                                                 │
│ [Clock]                                                                                   │
│ First Signal At   first_signal_at   Datetime RO      │ Tier          cert_in_tier  Select│
│ Confirmed At      confirmed_at      Datetime RO      │   R1 / R2 / R3 / None             │
│ Confirmed By      confirmed_by      Link User RO     │ Category      cert_in_category    │
│                                                      │               Select (Annexure I) │
│ Due At            cert_in_due_at    Datetime RO      │ Reported At   cert_in_reported_at │
│                                                      │               Datetime RO         │
│ Decision Reason   cert_in_decision_reason  Small Text (required for None)                 │
│ [Reports]                                                                                 │
│ Reports Sent      cert_in_reports   Table RO  Abuse Case CERT-In Report                   │
│                                                                                           │
│ {Operator}                                                                                │
│ [Resolution]                                                                              │
│ Resolution        resolution        Select           │ Closed At     closed_at     DT RO │
│   Fixed / False Positive / No Response /             │ Legal Hold    is_legal_hold Check │
│   Terminated / Suspended / Duplicate                 │                                   │
│ Operator Notes    operator_notes    Text Editor                                           │
│ [After Deletion]  (collapsed)                                                             │
│ Team Name         team_name         Data RO          │ Server Name   server_name  Data RO│
│ Owner Email       owner_email       Data RO          │                                   │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

Child tables:

| Child | Fields |
|---|---|
| Abuse Case Signal | `abuse_signal` Link Abuse Signal, `finding_code` Data (fetched), `severity` Select (fetched), `window_start` Datetime (fetched) |
| Abuse Case Restriction | `atlas_restriction_id` Data, `resource_action` Link Resource Action (the `idempotency_key`, empty for an emergency restriction), `kind` Select (egress_throttle, ingress_throttle, port_block, quarantine, isolate), `status` Select (Pending, Applied, Lifted, Failed), `applied_by` Select, `applied_by_user` Data, `applied_at` Datetime, `expires_at` Datetime, `ended_at` Datetime, `ended_by` Select (Central, Expiry, Atlas user) |
| Abuse Case Notification | `event_type` Data, `recipient` Data, `sent_at` Datetime, `result` Select (Sent, Failed), `error` Small Text |
| Abuse Case CERT-In Report | `kind` Select (Initial, Follow-up), `sent_at` Datetime, `sent_copy` Attach |

- Only the policy engine or an operator action sets the status, the ladder level, the deadlines, and the restrictions. Nobody edits them on the form.
- Central matches a `vm.restriction` event to a restriction row by `atlas_restriction_id`, and by `resource_action` when the name is not known yet. `ended_by` comes from `lifted_by` of the event. The Resource Action of a Central lift names the customer or the operator. See [Events from Atlas](ABUSE.md#events-from-atlas).
- The form is read only, except Resolution, Operator Notes, Legal Hold, and the CERT-In tier, category, and reason.
- An operator can set every resolution except Fixed. Central sets Fixed when a Resolved case closes itself. See [Lifecycle](ABUSE.md#lifecycle).
- The {Operator} and {CERT-In} tabs are hidden from customers. The dashboard API returns only the {Case} fields and a redacted signal list.
- A case for a public bucket sets `bucket` and leaves `server` empty. See [Public buckets](ABUSE.md#public-buckets).
- Central fills the "After Deletion" fields when the team or server is deleted, then clears the links. See [Deletion](ABUSE.md#deletion).

## Abuse Signal

Team-scoped: an indexed `team` field, `abuse_signal_query_conditions`, and `abuse_signal_has_permission`. Detection, feeds, Cargo reports, Abuse Reports, and operators write it. Naming: hash. `track_changes` on, for the review fields.

```text
┌ Abuse Signal 9f2c41e7a0 ──────────────────────────────────────────────────────────────────┐
│ [Signal]                                                                                  │
│ Team              team              Link Team RO     │ Finding Code  finding_code Data RO │
│ Server            server            Link VM RO       │ Severity      severity   Select RO │
│ Bucket            bucket            Data RO          │   Low / Medium / High / Critical   │
│ Region            region            Link Region RO   │ Source        source     Select RO │
│                                                      │   Detection / Feed / Cargo /       │
│                                                      │   Report / Operator                │
│ [Window]                                                                                  │
│ Window Start      window_start      Datetime RO      │ Shadow        is_shadow  Check RO  │
│ Window End        window_end        Datetime RO      │ Cargo Signal  cargo_signal_id      │
│                                                      │               Data RO              │
│ [Values]                                                                                  │
│ Values            values            JSON RO                                               │
│   counts, rates, top destination ports, destination prefixes truncated to /24             │
│ [Review]                                                                                  │
│ False Positive    is_false_positive Check            │ Reviewed By   reviewed_by Link RO  │
│ Review Note       review_note       Small Text                                            │
│ [After Deletion]  (collapsed)                                                             │
│ Team Name         team_name         Data RO          │ Server Name   server_name  Data RO │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

- Only the Review section is writable. Only `Abuse Responder` writes it.
- A signal for a public bucket or a site sets `bucket` or names the site in `values`, and leaves `server` empty.
- Detection moves `window_end` while the match continues. See [Signals](ABUSE.md#signals).
- `cargo_signal_id` holds the Cargo `signal_id`, so a repeated Cargo report updates the same row. See [Reports from Cargo](ABUSE.md#reports-from-cargo).
- Indexes in `on_doctype_update`: (`server`, `window_start`), (`finding_code`, `window_start`), and `cargo_signal_id`.
- The dashboard API returns a redacted list: finding code, severity, and window. It never returns the raw `values` or the review fields.

## Abuse Report

Not team-scoped. Only `Abuse Responder` reads it. Naming: `AR-.#####`.

```text
┌ Abuse Report AR-00877 ────────────────────────────────────────────────────────────────────┐
│ [Reporter]                                                                                │
│ Reporter Name     reporter_name     Data RO          │ Trust         reporter_trust Select│
│ Reporter Email    reporter_email    Data RO          │   Trusted / Known / Unknown       │
│ Channel           channel           Select RO        │ Received At   received_at   DT RO │
│   Email / Form                                       │ Message ID    message_id  Data RO │
│                                                                                           │
│ [Report]                                                                                  │
│ Category          category          Select           │ Status        status      Select  │
│   (same list as Abuse Case)                          │   New / Attributed / Partly       │
│                                                      │   Attributed / Unattributed /     │
│                                                      │   Duplicate / Rejected            │
│ [Items]                                                                                   │
│ Items             items             Table  Abuse Report Item                              │
│                                                                                           │
│ [Evidence]                                                                                │
│ Description       description       Text RO   (parsed body)                               │
│ Evidence for Customer  customer_evidence  Text   (redacted lines, editable before send)   │
│ Raw Message       raw_message       Attach RO (deleted 1 year after the case closes)      │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

| Child | Fields |
|---|---|
| Abuse Report Item | `address` Data, `hostname` Data, `port` Int, `event_time` Datetime, `server` Data (attributed VM name), `attribution_method` Select (Public IP History, NAT Log, Proxy Route, Site Record, Unknown), `abuse_case` Link Abuse Case |

- `abuse_case` is on each item, not on the report. See [Decided](#decided), item 2.
- The parser fills `customer_evidence` with the reporter's details removed. A responder can edit it before the notice goes out. Central never forwards raw attachments. See [Redaction](ABUSE.md#redaction).
- `message_id` drops duplicate deliveries of the same mail.

## Abuse Exception

Team-scoped: an indexed `team` field, `abuse_exception_query_conditions`, and `abuse_exception_has_permission`. A member with `security:manage` requests it on the server's Security tab. A responder approves it. Naming: `AE-.#####`. `track_changes` on.

```text
┌ Abuse Exception AE-00031 ─────────────────────────────────────────────────────────────────┐
│ [Exception]                                                                               │
│ Team              team              Link Team RO     │ Status        status      Select  │
│ Server            server            Link VM          │   Requested / Approved /          │
│ Finding Code      finding_code      Data             │   Rejected / Expired / Revoked    │
│ Effect            effect            Select           │ Multiplier    multiplier  Float   │
│   Multiplier / Disabled                              │   (shown for Multiplier)          │
│                                                                                           │
│ [Reason]                                                                                  │
│ Reason            reason            Small Text   e.g. "Authorised pentest of 203.0.113.0/24"│
│                                                                                           │
│ [Period]                                                                                  │
│ Starts At         starts_at         Datetime         │ Requested By  requested_by  Link RO│
│ Expires At        expires_at        Datetime (required, at most 90 days after start)      │
│                                                      │ Approved By   approved_by   Link RO│
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

- Detection reads approved exceptions until they expire or a responder revokes them. Central sends nothing to Atlas. See [Exceptions](ABUSE.md#exceptions).
- The controller refuses the `smtp_outbound` default block. See [Abuse Exception](ABUSE.md#abuse-exception).

## Abuse Threshold

Not team-scoped. Only `Abuse Responder` and `System Manager` read and write it. One record for each region and finding code. Naming: `AT-.#####`. `track_changes` on.

```text
┌ Abuse Threshold AT-00004 ─────────────────────────────────────────────────────────────────┐
│ [Threshold]                                                                               │
│ Region            region            Link Region      │ Mode          mode       Select    │
│ Finding Code      finding_code      Data             │   Off / Shadow / Active            │
│ Severity          severity          Select           │ Window (Minutes)  window_minutes   │
│   Low / Medium / High / Critical                     │                   Int (1 or more)  │
│ [Triggers]                                                                                │
│ Triggers          triggers          Table  Abuse Threshold Trigger                        │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

| Child | Fields |
|---|---|
| Abuse Threshold Trigger | `rule` Data (for example `udp_flood`), `parameter` Data (for example `transmit_packets_per_second`), `comparison` Select (Above, Below), `value` Float, `unit` Data, `window_minutes` Int (empty uses the parent window) |

- All triggers of one rule must match together. Rules of one finding code match separately. See [Thresholds](ABUSE.md#thresholds).
- (`region`, `finding_code`) is unique. The controller checks it, and `on_doctype_update` adds a unique index.
- `mode` is the calibration switch. Shadow writes signals with `is_shadow`. Active also sends them to the policy engine. See [Calibration](ABUSE.md#calibration).
- A window is at least 1 min. The controller refuses a shorter one.
- The starting values ship as fixtures, not as JSON defaults, so a region can use other values.

## Abuse Feed

Not team-scoped. Only `Abuse Responder` and `System Manager` read and write it. Naming: by `feed_name`.

```text
┌ Abuse Feed OpenPhish ─────────────────────────────────────────────────────────────────────┐
│ [Feed]                                                                                    │
│ Feed Name         feed_name         Data             │ Enabled       is_enabled  Check    │
│ Kind              kind              Select           │ Refresh (Minutes)  refresh_minutes │
│   Mining Pools / Spamhaus DROP / abuse.ch Feodo /    │                    Int             │
│   Tor / Safe Browsing / OpenPhish / URLhaus /        │                                    │
│   DNSBL / SNDS / Shadowserver                        │                                    │
│ URL               url               Data             │ Credential    credential Password  │
│ [Status]                                                                                  │
│ Last Fetched At   last_fetched_at   Datetime RO      │ Entries       entry_count  Int RO  │
│ Last Error        last_error        Small Text RO                                         │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

- A feed applies to all regions.
- Central keeps the fetched entries in the cache, not in a DocType.
- A fetch failure sets `last_error` and keeps the last good entries. See [Feeds](ABUSE.md#feeds).

## Public IP Assignment

Not team-scoped. Only `Abuse Responder` and `System Manager` read it. Nobody writes it in Desk. Append only. Naming: hash.

```text
┌ Public IP Assignment 3c81d05b9e ──────────────────────────────────────────────────────────┐
│ [Address]                                                                                 │
│ Address           address           Data RO          │ Version       version   Select RO  │
│ Region            region            Link Region RO   │   4 / 6                            │
│ [Holder]                                                                                  │
│ Server            server            Data RO          │ Attached At   attached_at  DT RO   │
│ Atlas VM ID       atlas_vm_id       Data RO          │ Detached At   detached_at  DT RO   │
│ Team              team              Data RO                                               │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

- The Virtual Machine controller writes the rows when `public_ipv4` or `public_ipv6` changes. See [Public IP history](ABUSE.md#public-ip-history).
- `server` and `team` are plain names, not Links, so the history stays after a deletion.
- Index in `on_doctype_update`: (`address`, `attached_at`). Attribution finds the row where `attached_at <= t < detached_at`, or where `detached_at` is empty.

## Port 25 Request

Team-scoped: an indexed `team` field, `port_25_request_query_conditions`, and `port_25_request_has_permission`, which reuse `_team_field_query_conditions` and `_team_field_has_permission`. A member with `security:manage` creates it on the server's Security tab. Central or a responder decides it. Naming: `P25-.#####`. `track_changes` on.

```text
┌ Port 25 Request P25-00012 ────────────────────────────────────────────────────────────────┐
│ [Request]                                                                                 │
│ Team              team              Link Team RO     │ Status        status      Select   │
│ Server            server            Link VM          │   Pending / Accepted /             │
│ Sending Domain    sending_domain    Data             │   Rejected / Revoked               │
│ Reverse DNS Name  reverse_dns_name  Data             │                                    │
│                                                                                           │
│ [Use]                                                                                     │
│ Purpose           purpose           Small Text                                            │
│ Bulk Mail Policy  bulk_mail_policy  Small Text                                            │
│                                                                                           │
│ [Decision]                                                                                │
│ Decided By        decided_by        Link User RO     │ Abuse Case    abuse_case  Link RO  │
│ Decided At        decided_at        Datetime RO      │   (set when a case revokes it)     │
│ Decision Reason   decision_reason   Small Text                                            │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

| Field | Type | Use |
|---|---|---|
| `team` | Link Team, indexed, RO | The team that owns the server |
| `server` | Link Virtual Machine | The server to unblock |
| `purpose` | Small Text | Why the server sends mail on port 25 |
| `sending_domain` | Data | The domain in the sender address |
| `reverse_dns_name` | Data | The reverse DNS name for the public IPv4 |
| `bulk_mail_policy` | Small Text | How the customer sends bulk mail, if at all |
| `status` | Select (Pending, Accepted, Rejected, Revoked) | Central and responders set it |
| `decided_by` | Link User, RO | The responder. Empty for an automatic acceptance. |
| `decided_at` | Datetime, RO | When the request was accepted, rejected, or revoked |
| `decision_reason` | Small Text | The reason for the decision |
| `abuse_case` | Link Abuse Case, RO | The case of the DNSBL listing or spam trap hit that revoked the request |

- A server has at most one open request. An open request is Pending or Accepted.
- Accepted sets `is_port_25_allowed` through an Atlas VM update. Revoked clears it. See [Email](ABUSE.md#email).

## Team (layout change)

A new section "Security" after "Members".

```text
│ [Security]                                                                                │
│ Security Contact Email  security_contact_email  Data (Email) │ Security Contact Name      │
│                                                              │  security_contact_name Data│
```

- Optional. The contact gets Security events only. See [Customer messages](ABUSE.md#engine-changes).
- Owners and admins edit it on the dashboard team settings page.

## Region (layout change)

A new section "Abuse" on the Cargo tab, after "State delivery". Fields that hold credentials are Password. An operator copies the values from Cargo. See [Reads from Datum](ABUSE.md#reads-from-datum) and [Reads from the log bucket](ABUSE.md#reads-from-the-log-bucket).

```text
│ {Cargo}                                                                                   │
│ [Abuse]                                                                                   │
│ Datum Query URL      datum_query_url            Data (URL)                                │
│ Datum Read User      datum_read_user            Data │ Datum Read Password                │
│                                                      │  datum_read_password  Password     │
│ Log Bucket Endpoint  abuse_log_bucket_endpoint  Data │ Log Bucket Name                    │
│                                                      │  abuse_log_bucket_name  Data       │
│ Log Read Key ID                                      │ Log Read Secret Key                │
│  abuse_log_read_access_key_id  Data                  │  abuse_log_read_secret_access_key  │
│                                                      │  Password                          │
```

- The read user and the read key are read only on the Cargo side. Central never writes to Datum or to the log bucket.
- An empty field stops detection, or log reads, for the region. The abuse dashboard names the region and the field.

## VM Snapshot (layout change)

A new field in the "Lifecycle" section, after `is_free`.

```text
│ [Lifecycle]                                                                               │
│ Deleted At        expires_at        Datetime         │ Abuse Evidence  is_abuse_evidence  │
│ Free              is_free           Check            │                 Check RO           │
```

- Central sets `is_abuse_evidence` on the snapshot that it takes before it terminates a server with an open case or an active restriction. See [Calls to Atlas](ABUSE.md#calls-to-atlas).
- The customer dashboard never lists a snapshot with `is_abuse_evidence`. The customer cannot delete it.
- Only `Abuse Responder` and `System Manager` read it. `Abuse Responder` does not write it.
- Central keeps it for 30 days, or longer on a legal hold. See [Records and retention](ABUSE.md#records-and-retention).

## Central Settings, tab "Abuse" (layout change)

No field has a default. See [Settings](ABUSE.md#settings).

```text
│ {Abuse}                                                                                   │
│ [Contacts]                                                                                │
│ Abuse Email       abuse_email           Data   │ Alert Webhook URL                        │
│                                                │  abuse_alert_webhook_url  Data           │
│ Trusted Reporters trusted_reporters     Small Text, one domain or address per line        │
│                                                │ Report Webhook URL                       │
│                                                │  abuse_report_webhook_url  Data          │
│ [Profiles]                                                                                │
│ Strict Multiplier strict_multiplier     Float  │ Relaxed Multiplier relaxed_multiplier    │
│                                                │                    Float                 │
│ [CERT-In Point of Contact]                                                                │
│ Name              cert_in_contact_name         │ Email          cert_in_contact_email     │
│ Designation       cert_in_contact_designation  │ Mobile         cert_in_contact_mobile    │
│ Organisation      cert_in_contact_organisation │ Phone          cert_in_contact_phone     │
│ Address           cert_in_contact_address      │ Fax            cert_in_contact_fax       │
│                   Small Text                   │                                          │
│ [CERT-In Reporting]                                                                       │
│ Incident Email    cert_in_incident_email  Data                                            │
```

- Port classes are not settings. They are a fixed list in metald, and Central keeps a copy in code. See [Metrics](ABUSE.md#metrics).
- Start the multipliers with 0.5 and 2. Detection does not run until both are set. See [Profiles](ABUSE.md#profiles).

## Decided

1. The only default block is `smtp_outbound`, a host rule on every VM with no VM Restriction row. `is_port_25_allowed` on the VM is its only exception. Central sets it when it accepts a Port 25 Request, and clears it when it revokes one.
2. Attribution is per item. Each Abuse Report Item links its own Abuse Case. The report status includes Partly Attributed.
3. The calibration switch is `mode` (Off, Shadow, Active) on the Central Abuse Threshold of each region and finding code. See [Abuse Threshold](#abuse-threshold).
4. Detection, signals, thresholds, profiles, exceptions, feeds, and public IP history are Central records. Atlas holds only VM Restriction, `is_port_25_allowed`, and Abuse Settings with the log bucket write keys. See [Atlas abuse layouts](https://github.com/frappe/atlas/blob/develop/docs/abuse/layouts.md).
