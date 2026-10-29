# Abuse layouts

## Purpose

This document holds the mockups for the new Central DocTypes and layout changes of [Abuse protection](ABUSE.md).

Status: awaiting engineer approval. Do not write DocType JSON before an engineer approves these layouts. Follow the Desk rules in [the repository guide](../CLAUDE.md#desk-and-operations).

The Atlas layouts (Abuse Signal, VM Restriction, Public IP Assignment, Abuse Settings, and the Virtual Machine change) are in [Atlas abuse layouts](https://github.com/frappe/atlas/blob/develop/docs/abuse/layouts.md).

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
│ Signals           signals           Table RO  Abuse Case Signal                           │
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
| Abuse Case Signal | `atlas_signal_id` Data, `cargo_signal_id` Data, `finding_code` Data, `severity` Select, `window_start` Datetime, `window_end` Datetime, `count` Int, `circuit_breaker` Data |
| Abuse Case Restriction | `atlas_restriction_id` Data, `kind` Select, `status` Select (Pending, Applied, Lifted, Failed), `applied_by` Select, `applied_by_user` Data, `applied_at` Datetime, `expires_at` Datetime, `ended_at` Datetime, `ended_by` Select (Central, Customer, Operator, Expiry) |
| Abuse Case Notification | `event_type` Data, `recipient` Data, `sent_at` Datetime, `result` Select (Sent, Failed), `error` Small Text |
| Abuse Case CERT-In Report | `kind` Select (Initial, Follow-up), `sent_at` Datetime, `sent_copy` Attach |

- Only the policy engine or an operator action sets the status, the ladder level, the deadlines, and the restrictions. Nobody edits them on the form.
- The form is read only, except Resolution, Operator Notes, Legal Hold, and the CERT-In tier, category, and reason.
- An operator can set every resolution except Fixed. Central sets Fixed when a Resolved case closes itself. See [Lifecycle](ABUSE.md#lifecycle).
- The {Operator} and {CERT-In} tabs are hidden from customers. The dashboard API returns only the {Case} fields and a redacted signal list.
- A case for a public bucket sets `bucket` and leaves `server` empty. See [Public buckets](ABUSE.md#public-buckets).
- Central fills the "After Deletion" fields when the team or server is deleted, then clears the links. See [Deletion](ABUSE.md#deletion).

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

Team-scoped, with the same hooks as Abuse Case. A member with `security:manage` requests it on the server's Security tab. A responder approves it. Naming: `AE-.#####`. `track_changes` on.

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

- Approval sends a VM Abuse Override row to Atlas. Expiry or revocation removes it.
- The controller refuses host safety codes and the default blocks. See [Abuse Exception](ABUSE.md#abuse-exception).

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

## Central Settings, tab "Abuse" (layout change)

No field has a default. See [Settings](ABUSE.md#settings).

```text
│ {Abuse}                                                                                   │
│ [Contacts]                                                                                │
│ Abuse Email       abuse_email           Data   │ Alert Webhook URL   abuse_alert_webhook_url│
│ Trusted Reporters trusted_reporters     Small Text, one domain or address per line        │
│                                                │ Report Webhook URL  abuse_report_webhook_url│
│ [CERT-In Point of Contact]                                                                │
│ Name              cert_in_contact_name         │ Email          cert_in_contact_email      │
│ Designation       cert_in_contact_designation  │ Mobile         cert_in_contact_mobile     │
│ Organisation      cert_in_contact_organisation │ Phone          cert_in_contact_phone      │
│ Address           cert_in_contact_address      │ Fax            cert_in_contact_fax        │
│                   Small Text                   │                                           │
│ [CERT-In Reporting]                                                                       │
│ Incident Email    cert_in_incident_email  Data                                            │
```

## Decided

1. Default blocks are host rules. `smtp_outbound` and `mining_pools` apply to every VM, with no VM Restriction rows. `is_port_25_allowed` on the VM is the only exception. Central sets it when it accepts a Port 25 Request, and clears it when it revokes one. `mining_pools` takes no exception.
2. Attribution is per item. Each Abuse Report Item links its own Abuse Case. The report status includes Partly Attributed.
3. The calibration switch is a `mode` (Off, Shadow, Active) for each finding code in Atlas. See [Atlas abuse layouts](https://github.com/frappe/atlas/blob/develop/docs/abuse/layouts.md).
