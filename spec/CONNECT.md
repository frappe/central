# Frappe Connect integration

## Purpose

This document is the contract between Central and Frappe Connect. Connect is the marketplace where a customer finds a partner. Central is where the customer's team, servers, and access live.

Status: planned. Central does not implement this contract yet. Connect can build against it now. Change this document before you change the contract.

## Who owns what

| Fact | Owner | Record |
|---|---|---|
| Who is a partner | Connect | Connect's Partner |
| The commercial deal between a partner and a customer | Connect | Connect's Engagement |
| Which Central team belongs to a partner | Central | `Team.connect_partner_id` |
| Whether a partner team can act on a customer team, and with which role | Central | Partner Link |
| What a person can do on a team | Central | Team Member, Team Role, and Partner Link, resolved by `central/iam.py` |

Connect is the authority on who is a partner. The customer is the authority on what the partner can do. Central enforces both.

## Communication

Connect calls Central. Central never calls Connect, and Central never reads Connect's data.

```text
Connect ──HTTPS, Authorization: token <api key>:<api secret>──▶ Central /api/method/central.api.connect.*
Connect ◀──────────────────────────── JSON ───────────────────── Central
```

Central mints the only credential. It is a standard Frappe API key on one integration user.

| Item | Value |
|---|---|
| User | `connect@integration`, a System User with no other roles |
| Role | `Connect Integration` |
| Credential | The API key and API secret of that user, generated in desk |
| Allowed routes | Only `central.api.connect.*`. Each route starts with `frappe.only_for("Connect Integration")`. |
| Rotation | Generate new keys on the user. The old secret stops working at once. |
| Kill switch | Disable the user. Every Connect call fails with HTTP 401. |

Connect keeps the secret in its site configuration. Do not put the secret in a URL, a log, or a browser.

Example:

```bash
curl -X POST https://central.example.com/api/method/central.api.connect.create_partner_link \
  -H "Authorization: token 1a2b3c4d5e:6f7g8h9i0j" \
  -H "Content-Type: application/json" \
  -d '{"connect_partner_id": "PTR-0001", "engagement_id": "ENG-0042", "customer_email": "ops@northwind.example", "project_title": "Manufacturing implementation", "return_url": "https://connect.example.com/projects/ENG-0042"}'
```

## Configuration

| Setting | Where | Use |
|---|---|---|
| Connect URL | Central Settings | Central accepts a `return_url` only when its host is this host. This stops an open redirect. |
| Invitation Expiry (Days) | Central Settings | A Partner Registration or a Partner Link that nobody answers expires after this many days. |

## Records

### Team

A team is a partner team when `connect_partner_id` is set. Only a completed Partner Registration sets it. The field is read-only in desk. One Connect partner maps to one team.

### Partner Registration

A request for the owner of a partner to choose their Central team.

| Field | Value |
|---|---|
| `connect_partner_id` | Connect's partner ID. Unique. |
| `partner_name` | The name Connect shows for the partner |
| `owner_email` | The email of the person who must confirm |
| `token` | A random value. It is the only key the landing page reads. |
| `status` | `Pending`, `Completed`, or `Expired` |
| `team` | The team the owner chose, after completion |

### Partner Link

The relationship between one partner team and one customer team, for one engagement.

| Field | Value |
|---|---|
| `engagement_id` | Connect's engagement ID. Unique. |
| `partner_team` | The partner's team |
| `customer_email` | The email of the customer who must answer |
| `customer_team` | The team the customer chose, after acceptance |
| `project_title` | The title the customer sees |
| `return_url` | Where the customer goes back to in Connect |
| `token` | A random value. It is the only key the landing page reads. |
| `status` | See [Partner Link states](#partner-link-states) |
| `role` | The customer team role the partner gets: `Developer` or `Viewer` |
| `ended_by`, `ended_on`, `end_reason` | Who ended the link, when, and why |

## Endpoints

All endpoints use `POST` and return JSON in `message`. A repeated call with the same `connect_partner_id` or `engagement_id` returns the existing record, so a retry is safe.

### `central.api.connect.register_partner`

Ask the owner of a partner to choose the Central team that represents the partner.

| Argument | Required | Value |
|---|---|---|
| `connect_partner_id` | Yes | Connect's partner ID |
| `partner_name` | Yes | The partner's display name |
| `owner_email` | Yes | The owner's email |

```json
{"message": {"status": "Pending", "url": "https://central.example.com/dashboard/connect/partner/k3Jd9..."}}
```

When the registration is already `Completed`, the response has `status` and `team`, and no `url`.

### `central.api.connect.create_partner_link`

Ask a customer to accept a partner on their team.

| Argument | Required | Value |
|---|---|---|
| `connect_partner_id` | Yes | A partner with a `Completed` registration |
| `engagement_id` | Yes | Connect's engagement ID |
| `customer_email` | Yes | The customer's email |
| `project_title` | Yes | The title the customer sees |
| `return_url` | Yes | A URL on the configured Connect host |

```json
{"message": {"status": "Requested", "url": "https://central.example.com/dashboard/connect/customer/Qm81x..."}}
```

### `central.api.connect.get_partner_link`

Read the state of a link.

| Argument | Required | Value |
|---|---|---|
| `engagement_id` | Yes | Connect's engagement ID |

```json
{"message": {"status": "Active", "customer_team": "TEAM-00012", "role": "Developer", "ended_by": null, "ended_on": null}}
```

### `central.api.connect.end_partner_link`

End a link. Use it when the engagement ends or is cancelled in Connect.

| Argument | Required | Value |
|---|---|---|
| `engagement_id` | Yes | Connect's engagement ID |
| `reason` | Yes | A short sentence. The other team's owner reads it. |

```json
{"message": {"status": "Ended"}}
```

Ending a link that is already `Ended`, `Declined`, or `Expired` returns its status and changes nothing.

### Errors

| HTTP status | Frappe exception | Cause |
|---|---|---|
| 401 | `AuthenticationError` | The API key or secret is wrong, or the integration user is disabled. |
| 403 | `PermissionError` | The user does not have the `Connect Integration` role. |
| 404 | `DoesNotExistError` | No Partner Link has this `engagement_id`. |
| 417 | `ValidationError` | An argument is missing or wrong, the partner is not registered, or the `return_url` host is not the Connect host. The message says which. |

## Partner registration flow

1. Connect calls `register_partner` and sends the `url` to the partner's owner.
2. The owner opens the URL and signs in to Central.
3. If the signed-in email is not `owner_email`, Central shows an error and stops.
4. The owner chooses one of the teams they own, or creates a team.
5. Central sets `Team.connect_partner_id` and marks the registration `Completed`.

## Customer flow

1. Connect calls `create_partner_link` and shows the `url` as "Log in to Frappe Cloud".
2. The customer opens the URL. If they are not signed in, Central sends them to sign in or sign up and back to the URL after.
3. If the signed-in email is not `customer_email`, Central shows an error and stops.
4. If the customer has no team, the onboarding dialog asks them to create one.
5. The onboarding dialog shows the partner step: the partner's name and logo, the project title, Accept, and Decline.
6. If the customer accepts, they choose the team when they own more than one, and the role: `Developer` or `Viewer`.
7. Central sets the link to `Active` or `Declined` and shows a button back to `return_url`.
8. Connect calls `get_partner_link` to read the result.

Example: Frappe is a partner. Northwind accepts Frappe for "Manufacturing implementation" with the `Developer` role. Frappe staff with partner access can now manage Northwind's servers. They cannot change Northwind's members or billing.

## Partner Link states

```text
Requested ──customer accepts──▶ Active ──ended──▶ Ended
    │
    ├──customer declines──▶ Declined
    ├──nobody answers before expiry──▶ Expired
    └──ended──▶ Ended
```

Only the customer can make a link `Active` or change its role. Ending removes access, so more than one party can do it:

| Who | Where | Capability |
|---|---|---|
| The customer team owner | Central, Team, Partners, Remove partner | `team:manage_partners` on the customer team |
| The partner team owner | Central, Customers, Stop working with this customer | `team:manage_partners` on the partner team |
| Connect | `end_partner_link` | `Connect Integration` |
| Central | When the customer team is deleted, or the partner team loses `connect_partner_id` | None |

Central never makes an `Ended`, `Declined`, or `Expired` link active again. A new engagement creates a new Partner Link, so each period of access has its own record.

## Partner access

A partner staff member can act on a customer team only when all of these rules pass:

1. The staff member holds `partner:act_on_customers` in the partner team.
2. A Partner Link from the partner team to the customer team is `Active`.
3. The capability is in the link's `role`.
4. The capability is not in the list that a partner can never get.

A partner can never get these capabilities on a customer team:

- `team:edit`
- `team:manage_members`
- `team:delete`
- `team:manage_partners`
- `billing:manage`

The partner staff member is never a member of the customer team. A change to the partner team's members applies to every customer at once. The customer's activity log shows each action with the staff member and the partner team.

## What ending a link does

| Area | Result |
|---|---|
| Console and API access | The next request from partner staff is refused. The customer team leaves their team switcher. |
| Open sessions on the customer's sites | Central asks Pilot to end the sessions of partner staff on the customer's sites. |
| SSH keys that partner staff added | Central removes them from the customer's servers. |
| Servers and sites the partner created | They stay with the customer. The customer team owns everything in it. |
| History | The link keeps `ended_by`, `ended_on`, and `end_reason`. The activity log keeps every action. |
| Notification | Central sends an email to the owner of the other team. Connect reads the change with `get_partner_link`. |

## Not in this contract

- Billing through the partner. The partner pays the customer's invoices. This needs its own billing design.
- Promotional credits for partner customers.
- A push from Central to Connect. If Central must push later, Central signs the request and Connect checks it against Central's JWKS.

## Changes to this contract

This document is the contract. There is no version field. To change the contract:

1. Change this document in a pull request to Central.
2. Get a review from the Connect developers.
3. Deploy Central before Connect starts to use a new endpoint or argument.
