# Abuse layouts

## Purpose

This document holds the mockups for the new Central DocTypes and layout changes of [Abuse protection](ABUSE.md).

Status: awaiting engineer approval. Do not write DocType JSON before an engineer approves these layouts. Follow the Desk rules in [the repository guide](../CLAUDE.md#desk-and-operations).

The Atlas layouts are in [Atlas abuse layouts](https://github.com/frappe/atlas/blob/develop/docs/abuse/layouts.md). The Watcher layouts (Abuse Threshold and Abuse Feed) are in [Cargo Watcher layouts](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#layouts).

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
│ Blocked Scope     blocked_scope     Select RO        │ Blocked User     blocked_user     │
│   VM / Team / Account                                │                  Link User RO     │
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
| Abuse Case Restriction | `server` Link VM (the VM of the entry: the server of the case, or another VM of the team for a team block), `restriction_id` Data (the entry ID in the Metal VM network object: the Resource Action name, or the `atlas-` ID of an emergency restriction), `resource_action` Link Resource Action (the `idempotency_key`, empty for an emergency restriction), `kind` Select (egress_throttle, ingress_throttle, port_block, quarantine, isolate), `status` Select (Pending, Saved, Applied, Failed, Lifted, Expired), `desired_generation` Int (from the Atlas response), `error` Small Text (the Atlas error or `host_error`), `applied_by` Select, `applied_by_user` Data, `applied_at` Datetime, `expires_at` Datetime, `ended_at` Datetime, `ended_by` Select (Central, Expiry, Atlas operator) |
| Abuse Case Notification | `event_type` Data, `recipient` Data, `sent_at` Datetime, `result` Select (Sent, Failed), `error` Small Text |
| Abuse Case CERT-In Report | `kind` Select (Initial, Follow-up), `sent_at` Datetime, `sent_copy` Attach |

- Only the policy engine or an operator action sets the status, the ladder level, the deadlines, and the restrictions. Nobody edits them on the form.
- Central sets the restriction `status` from the Atlas response and from the repair scan of the Atlas `GET` VM response. Central derives `ended_by`: Central for its own lift, Expiry at `expires_at`, and Atlas operator for an entry that left the network before `expires_at`. The Resource Action of a Central lift names the customer or the operator. See [Restriction states](ABUSE.md#restriction-states).
- Central sets `blocked_scope` (VM, Team, or Account) when it restricts something for the case. It is empty before that. `blocked_user` is set only for an account block. A team block is a field on the case, not a DocType. See [Team and account blocks](ABUSE.md#team-and-account-blocks).
- The form is read only, except Resolution, Operator Notes, Legal Hold, and the CERT-In tier, category, and reason.
- An operator can set every resolution except Fixed. Central sets Fixed when a Resolved case closes itself. See [Lifecycle](ABUSE.md#lifecycle).
- The {Operator} and {CERT-In} tabs are hidden from customers. The dashboard API returns only the {Case} fields and a redacted signal list.
- A case for a public bucket sets `bucket` and leaves `server` empty. See [Public buckets](ABUSE.md#public-buckets).
- Central fills the "After Deletion" fields when the team or server is deleted, then clears the links. See [Deletion](ABUSE.md#deletion).

## Abuse Signal

Team-scoped: an indexed `team` field, `abuse_signal_query_conditions`, and `abuse_signal_has_permission`. Watcher findings, brand-term scoring, Abuse Reports, and operators write it. Naming: hash. `track_changes` on, for the review fields.

```text
┌ Abuse Signal 9f2c41e7a0 ──────────────────────────────────────────────────────────────────┐
│ [Subject]                                                                                 │
│ Team              team              Link Team RO     │ Finding Code  finding_code Data RO │
│ Server            server            Link VM RO       │ Severity      severity   Select RO │
│ Bucket            bucket            Data RO          │   Low / Medium / High / Critical   │
│ Hostname          hostname          Data RO          │ Source        source     Select RO │
│ Address           address           Data RO          │   Watcher / Brand Scoring /        │
│ Region            region            Link Region RO   │   Report / Operator                │
│ [Window]                                                                                  │
│ Window Start      window_start      Datetime RO      │ Shadow        is_shadow  Check RO  │
│ Window End        window_end        Datetime RO      │ Finding ID    finding_id Data RO   │
│ Trusted Source    is_trusted_source Check RO                                              │
│ [Values]                                                                                  │
│ Measured          measured          JSON RO          │ Threshold     threshold  JSON RO   │
│   one value for each volume trigger                  │                                    │
│ Evidence          evidence          JSON RO                                               │
│   port class, ports, protocol, counts, ratios, prefixes, feed, feed entry, log writer     │
│ [Review]                                                                                  │
│ False Positive    is_false_positive Check            │ Reviewed By   reviewed_by Link RO  │
│ Review Note       review_note       Small Text                                            │
│ [After Deletion]  (collapsed)                                                             │
│ Team Name         team_name         Data RO          │ Server Name   server_name  Data RO │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

- Only the Review section is writable. Only `Abuse Responder` writes it.
- A signal sets the subject of the finding: `server`, `bucket`, `hostname`, or `address`. A site signal also sets the `server` of the site.
- `finding_id`, `measured`, `threshold`, `evidence`, `is_shadow`, and `is_trusted_source` come from the Watcher finding. See [Reports from Cargo](ABUSE.md#reports-from-cargo).
- `measured` and `threshold` hold one value for each volume trigger of the rule. Both are empty for a feed match or a stratum match. Ratios are in `evidence`. See [Profiles](ABUSE.md#profiles).
- `is_trusted_source` is set when the finding comes from an Abuse Feed with `is_trusted`. Central can then suspend a phishing site automatically. See [Phishing sites](ABUSE.md#phishing-sites).
- A repeated `finding_id` updates the same row and moves `window_end`. See [Signals](ABUSE.md#signals).
- A signal with `is_shadow` opens no case.
- Indexes in `on_doctype_update`: (`server`, `window_start`), (`finding_code`, `window_start`), and `finding_id`.
- The dashboard API returns a redacted list: finding code, severity, and window. It never returns the raw `evidence` or the review fields.

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
| Abuse Report Item | `address` Data, `hostname` Data, `port` Int, `event_time` Datetime, `server` Data (name of the attributed Central Virtual Machine, as plain text), `attribution_method` Select (Public IP History, NAT Port Range, Proxy Route, Site Record, Unknown), `abuse_case` Link Abuse Case |

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

- Central applies approved exceptions to findings until they expire or a responder revokes them. Central sends nothing to Watcher or Atlas. See [Exceptions](ABUSE.md#exceptions).
- The controller refuses a multiplier below 0.5, the level from which Watcher reports. See [Profiles](ABUSE.md#profiles).
- An exception cannot open the mail ports. See [Abuse Exception](ABUSE.md#abuse-exception).

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

## Mail Port Request

Team-scoped: an indexed `team` field, `mail_port_request_query_conditions`, and `mail_port_request_has_permission`, which reuse `_team_field_query_conditions` and `_team_field_has_permission`. A member with `security:manage` creates it on the server's Security tab. Central or a responder decides it. Naming: `MPR-.#####`. `track_changes` on.

```text
┌ Mail Port Request MPR-00012 ──────────────────────────────────────────────────────────────┐
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
| `purpose` | Small Text | Why the server uses ports 25, 465, and 587 |
| `sending_domain` | Data | The domain in the sender address |
| `reverse_dns_name` | Data | The reverse DNS name for the public IPv4 |
| `bulk_mail_policy` | Small Text | How the customer sends bulk mail, if at all |
| `status` | Select (Pending, Accepted, Rejected, Revoked) | Central and responders set it |
| `decided_by` | Link User, RO | The responder. Empty for an automatic acceptance. |
| `decided_at` | Datetime, RO | When the request was accepted, rejected, or revoked |
| `decision_reason` | Small Text | The reason for the decision |
| `abuse_case` | Link Abuse Case, RO | The case of the DNSBL listing or spam trap hit that revoked the request |

- A server has at most one open request. An open request is Pending or Accepted.
- Central sets `is_mail_ports_blocked` in every VM create request.
- Accepted clears `is_mail_ports_blocked` through the Atlas mail ports route. Revoked sets it again through the same route. See [Email](ABUSE.md#email).
- A VM created before the rollout has the mail ports open and needs no request. Central blocks it on a DNSBL finding or a spam finding, or when a responder sets the block.

## Team (layout change)

A new section "Security" after "Members".

```text
│ [Security]                                                                                │
│ Security Contact Email  security_contact_email  Data (Email) │ Security Contact Name      │
│                                                              │  security_contact_name Data│
```

- Optional. The contact gets Security events only. See [Customer messages](ABUSE.md#engine-changes).
- Owners and admins edit it on the dashboard team settings page.

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
│ [CERT-In Point of Contact]                                                                │
│ Name              cert_in_contact_name         │ Email          cert_in_contact_email     │
│ Designation       cert_in_contact_designation  │ Mobile         cert_in_contact_mobile    │
│ Organisation      cert_in_contact_organisation │ Phone          cert_in_contact_phone     │
│ Address           cert_in_contact_address      │ Fax            cert_in_contact_fax       │
│                   Small Text                   │                                          │
│ [CERT-In Reporting]                                                                       │
│ Incident Email    cert_in_incident_email  Data                                            │
```

- Port classes are not settings. They are a fixed list in metald, and Central keeps a copy in code. See [Restrictions](ABUSE.md#restrictions).
- The profile multipliers are not settings. They are constants in code, because the strict multiplier must equal the level from which Watcher reports. See [Profiles](ABUSE.md#profiles).

## Decided

1. The mail ports 25, 465, and 587 are blocked only when Central asks. `is_mail_ports_blocked` is a field of the Metal VM network object, and a missing field means open. The block applies to new TCP flows in both directions, only to remote addresses outside the mesh prefix list. Central sets it in every VM create request. Central clears it when it accepts a Mail Port Request, and sets it again when it revokes one, through the Atlas mail ports route. VMs created before the rollout keep the mail ports open until a DNSBL finding, a spam finding, or a responder sets the block.
2. Attribution is per item. Each Abuse Report Item links its own Abuse Case. The report status includes Partly Attributed.
3. The calibration switch is `mode` (Off, Shadow, Active) on the Cargo Abuse Threshold of each finding code. Central stores a shadow finding and takes no action. See [Cargo calibration](https://github.com/frappe/cargo/blob/develop/docs/watcher.md#calibration).
4. Signals, profiles, exceptions, and public IP history are Central records. Finding codes, thresholds, and feeds are Cargo records. See [Cargo Watcher](https://github.com/frappe/cargo/blob/develop/docs/watcher.md). Atlas keeps no abuse record. Restrictions and `is_mail_ports_blocked` are in the Metal VM network object. Atlas Settings holds the log bucket name and endpoint. See [Atlas abuse layouts](https://github.com/frappe/atlas/blob/develop/docs/abuse/layouts.md).
5. Team and account blocks are fields on the Abuse Case: `blocked_scope` (VM, Team, or Account) and `blocked_user`. There is no separate DocType. Each VM of a team block has its own Abuse Case Restriction row, with `server` set. See [Team and account blocks](ABUSE.md#team-and-account-blocks).
