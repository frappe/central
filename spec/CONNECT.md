# Frappe Connect integration

## Purpose

This document is the contract between Central and Frappe Connect. Connect is the partner portal and marketplace. Central is where teams, servers, access, and invoices live.

Status: planned. Central does not implement this contract yet. Connect `main` has a client for an earlier version of it in `connect/partner/cloud_integration.py`. Change this document before you change the contract.

## Who owns what

| Fact | Owner | Record |
|---|---|---|
| Who is a partner, and its tier | Connect | Connect's Partner |
| The commercial deal between a partner and a customer | Connect | Connect's Project Quote and Partner Customer |
| Which Central team belongs to a partner, and its partner code | Central | `Team.connect_partner_id`, `Team.partner_code` |
| Whether a partner is linked to a customer team, with which role, and who pays | Central | Partner Link |
| Which partner an invoice counts for, and who pays it | Central | `Invoice.partner_team`, `Invoice.payer_team` |
| What a person can do on a team | Central | Team Member, Team Role, and Partner Link, resolved by `central/iam.py` |

Connect is the authority on who is a partner. The customer is the authority on what the partner can do and on who pays. Central enforces both.

## Communication

Connect calls Central. Central never calls Connect, and Central never reads Connect's data. When Connect is down, Central works without change.

```text
Connect ──HTTPS, Authorization: token <api key>:<api secret>──▶ Central /api/method/central.api.connect.*
Connect ◀──────────────────────────── JSON ───────────────────── Central
```

Central mints the only credential. It is a standard Frappe API key on one integration user.

| Item | Value |
|---|---|
| User | `connect@integration.localhost`, a System User with no other roles. Frappe needs a domain suffix in a User email. |
| Role | `Connect Integration` |
| Allowed routes | Only `central.api.connect.*`. Each route starts with `frappe.only_for("Connect Integration")`. |
| Rotation | Generate new keys on the user. The old secret stops working at once. |
| Kill switch | Disable the user. Every Connect call fails with HTTP 401. |

Connect keeps the secret in its Integration Settings (`cloud_site_url`, `cloud_api_key`, `cloud_api_secret`). Connect cannot create a link, set a role, or set who pays. It can register a partner, read, and end a link.

## Configuration

| Setting | Where | Use |
|---|---|---|
| Connect URL (`connect_url`) | Central Settings, Frappe Connect section | Central accepts a `return_url` only when its host is this host. This stops an open redirect. |
| Invitation Expiry (Days) (`invitation_expiry_days`) | Central Settings | A Partner Registration that nobody completes expires after this many days. Connect sends a new one after 14 days. |

## Records

### Team

| Field | Value |
|---|---|
| `connect_partner_id` | Connect's partner ID. Unique. Set only by a completed Partner Registration or by the Press migration. Read-only in desk. |
| `partner_code` | The code a customer enters to add this partner. Unique. Central generates it when `connect_partner_id` is set. A partner that comes from Press keeps its Press `partner_referral_code`. |

A team is a partner team when `connect_partner_id` is set. One Connect partner maps to one team.

### Partner Registration

A request for the admin of a partner to choose their Central team.

| Field | Value |
|---|---|
| `connect_partner_id` | Connect's partner ID. Unique. |
| `partner_name` | The name Connect shows for the partner |
| `owner_email` | The email of the person who must confirm |
| `return_url` | Where the admin goes back to in Connect. Optional. |
| `token` | A random value. It is the only key the landing page reads. |
| `status` | `Pending`, `Completed`, or `Expired` |
| `team` | The team the admin chose, after completion |
| `expires_on` | The day after which the link stops working |
| `completed_on` | When the admin chose the team |

### Partner Link

The relationship between one partner team and one customer team.

| Field | Value |
|---|---|
| `partner_team` | The partner's team |
| `customer_team` | The customer's team |
| `status` | `Active` or `Ended` |
| `role` | A Team Role of the customer team, or empty for no access. See [Partner access](#partner-access). |
| `payer` | `Customer`, `Partner Requested`, or `Partner`. See [Partner pays](#partner-pays). |
| `reference` | An opaque value from Connect's deep link, normally the Partner Customer ID. Empty when the customer typed the code. |
| `linked_by`, `linked_on` | The customer user who added the partner, and when |
| `ended_by`, `ended_on`, `end_reason` | Who ended the link, when, and why |

Rules:

- A customer team has at most one `Active` link. The customer ends the current link before they add another partner.
- A partner team cannot link to itself.
- Central never makes an `Ended` link active again. A new link is a new record, so each period has its own history.

### Invoice

| Field | Value |
|---|---|
| `partner_team` | The partner team of the customer's `Active` link when the invoice is generated. Empty when there is none. |
| `payer_team` | The team that pays. It is the partner team when the link's `payer` is `Partner` at generation. Empty means the invoice's own team pays. |

Both fields are a snapshot. A later change to the link does not change an existing invoice.

## Endpoints

All endpoints use `POST` and return JSON in `message`. A repeated call is safe.

### `central.api.connect.register_partner`

Ask the admin of a partner to choose the Central team that represents the partner.

| Argument | Required | Value |
|---|---|---|
| `connect_partner_id` | Yes | Connect's partner ID |
| `partner_name` | Yes | The partner's display name |
| `owner_email` | Yes | The admin's email |
| `return_url` | No | A URL on the configured Connect host |

```json
{"message": {"status": "Pending", "url": "https://central.example.com/dashboard/partner-registration/k3Jd9..."}}
```

When the registration is `Completed`, the response is `{"status": "Completed", "team": "TEAM-00007", "partner_code": "TRI-48213"}` and has no `url`.

### `central.api.connect.get_partner_registration`

Read the state of a registration. The status is `Completed` only while a team holds the `connect_partner_id`. A registration that is past `expires_on`, or whose team an operator removed from the program, is `Expired`. Connect then calls `register_partner` again.

| Argument | Required | Value |
|---|---|---|
| `connect_partner_id` | Yes | Connect's partner ID |

```json
{"message": {"status": "Completed", "team": "TEAM-00007", "partner_code": "TRI-48213"}}
```

### `central.api.connect.get_partner_customers`

List the links of one partner. Connect uses it for the Customers page and to learn about new and ended links.

| Argument | Required | Value |
|---|---|---|
| `connect_partner_id` | Yes | A partner with a `Completed` registration |
| `modified_after` | No | Return only links changed after this datetime |

```json
{"message": [{
  "link": "PLINK-00031", "reference": "PCUST-00012", "status": "Active",
  "customer_team": "TEAM-00012", "customer_team_name": "Northwind", "customer_email": "ops@northwind.example",
  "role": "Developer", "payer": "Customer", "linked_on": "2026-11-14 10:02:11", "ended_on": null,
  "currency": "INR", "mrr": 11500,
  "sites": [{"name": "northwind.frappe.cloud", "plan": "Business", "amount": 9000, "status": "Active", "region": "Mumbai"}]
}]}
```

`sites` and `mrr` are empty when the link's `role` is empty and its `payer` is `Customer`. The customer gave the partner no view of the account.

### `central.api.connect.get_partner_invoices`

List the paid invoices that count for one partner. Connect uses it for the Invoicing page and the tier.

| Argument | Required | Value |
|---|---|---|
| `connect_partner_id` | Yes | A partner with a `Completed` registration |
| `paid_after` | No | Return only invoices paid after this datetime |

```json
{"message": [{
  "invoice": "INV-2026-00418", "customer_team": "TEAM-00012", "customer_team_name": "Northwind",
  "period_start": "2026-10-01", "period_end": "2026-10-31", "paid_at": "2026-11-03 04:10:00",
  "currency": "INR", "amount": 11500, "paid_by_partner": false,
  "url": "https://central.example.com/dashboard/billing/invoices/INV-2026-00418"
}]}
```

`amount` is the invoice amount after discount and before tax. The list has every `Paid`, `Billable` invoice where `partner_team` is the partner's team. It also has the invoices of the partner's own team.

### `central.api.connect.end_partner_link`

End a link. Connect calls it when the partner marks the customer as churned, or when Connect removes the partner from the program.

| Argument | Required | Value |
|---|---|---|
| `link` | Yes | The Partner Link name from `get_partner_customers` |
| `reason` | Yes | A short sentence. The other team's owner reads it. |

```json
{"message": {"status": "Ended"}}
```

Ending a link that is already `Ended` returns its status and changes nothing.

### Errors

| HTTP status | Frappe exception | Cause |
|---|---|---|
| 401 | `AuthenticationError` | The API key or secret is wrong, or the integration user is disabled. |
| 403 | `PermissionError` | The user does not have the `Connect Integration` role. |
| 404 | `DoesNotExistError` | No record has this ID. |
| 417 | `ValidationError` | An argument is missing or wrong, the partner is not registered, or the `return_url` host is not the Connect host. The message says which. |

## Flows

### A partner registers

A partner needs a Central team before a customer can add it. The partner's admin does not need a Central account in advance.

1. Connect calls `register_partner`. This happens in the Frappe Cloud step of partner onboarding, or when a customer hires a partner that has not registered.
2. The admin opens the URL. If they have no Central account, they sign up with an email code.
3. If the signed-in email is not `owner_email`, Central shows an error and stops.
4. The admin chooses one of the teams they own, or creates a team. Central does not ask for a payment method.
5. Central sets `Team.connect_partner_id` and `Team.partner_code`, marks the registration `Completed`, and sends the admin to `return_url`.
6. Connect calls `get_partner_registration` and stores the partner code.

### A customer adds a partner

The customer always starts the link, in Central, with the partner code.

1. The customer opens Team, Partners, Add partner. There are two ways to get there:
   - From Connect: the project page shows "Log in to Frappe Cloud". It opens `/dashboard/partners/add?code=<partner code>&reference=<Partner Customer ID>`.
   - Directly: the partner gives the customer the code, as on Press.
2. If the customer is not signed in, Central sends them to sign in or sign up and back to the page. If they have no team, the onboarding dialog asks them to create one first.
3. Central shows the partner's team name and logo for the code. An unknown code shows an error.
4. The customer chooses the team when they own more than one, the role, and who pays.
5. Central creates the Partner Link as `Active`. No approval from the partner is necessary for access or attribution.
6. Connect reads the link with `get_partner_customers` on its next sync.

`code` and `reference` in the URL are untrusted input. Central checks the code against `Team.partner_code` and stores `reference` as text. Connect must ignore a `reference` that is not a Partner Customer of that partner.

Example: Northwind hires Tridots on Connect. Northwind opens the link, signs up, creates a team, and adds Tridots with the `Developer` role and "I pay". Tridots staff with partner access can now manage Northwind's servers. They cannot change Northwind's members or billing.

### Cases

| Case | What happens |
|---|---|
| The customer hires a partner on Connect | Deep link with `code` and `reference`. Connect matches the link to its Partner Customer by `reference`. |
| The partner brings its own client | The customer types the code. The link has no `reference`. Connect creates a Partner Customer with source `Own` from `customer_team_name` and `customer_email`. |
| The partner has no Central team | The partner has no code. Connect registers the partner first and shows the customer "Waiting for partner" until the registration is `Completed`. |
| The customer has no Central account | Central signs them up and returns them to the Add partner page. |
| The customer changes partner | The customer ends the current link and adds the new code. Each invoice keeps the partner it had at generation. |
| A partner staff member leaves | The partner removes them from its team. They lose every customer at once. |
| Connect removes a partner from the program | Connect calls `end_partner_link` for each link. An operator clears `connect_partner_id` in desk. |
| The partner hosts a client that wants no account | No link. The partner creates the servers in its own team and groups them in one Project per client. |
| A customer moves from Press | See [Press migration](#press-migration). |

## Partner access

A partner staff member can act on a customer team only when all of these rules pass:

1. The staff member holds `partner:act_on_customers` in the partner team.
2. A Partner Link from the partner team to the customer team is `Active`.
3. The link's `role` is not empty, and the capability is in that role.
4. The capability is not in the list that a partner can never get.

A partner can never get these capabilities on a customer team:

- `team:edit`
- `team:manage_members`
- `team:delete`
- `team:manage_partners`
- `billing:manage`

Capabilities:

| Capability | Default roles | Use |
|---|---|---|
| `partner:act_on_customers` | Owner, Admin, Developer | Act on the customer teams linked to this partner team |
| `team:manage_partners` | Owner, Admin | Add a partner, change its role or payer, end a link, accept or stop partner pays |

The role on a link:

- The customer chooses `Viewer`, `Developer`, a custom role of their team, or no access. Central does not offer `Owner`, `Admin`, or `Billing`.
- There is no separate partner role. A partner that wants to keep a staff member away from customers gives them a custom role without `partner:act_on_customers`.
- The Add partner page must say that `Developer` can create and terminate servers.

The partner staff member is never a member of the customer team. The customer team appears in their team switcher with the partner's name. The customer's activity log shows each action with the staff member and the partner team.

Connect's own roster (`Connect Partner Member.access`) controls Connect pages only. Central does not read it.

## Partner pays

The customer decides who pays. The partner must accept, because the partner takes the liability.

1. The customer sets "My partner pays" on the link. `payer` becomes `Partner Requested`. The customer still pays.
2. A partner user with `team:manage_partners` accepts in Central, Customers. `payer` becomes `Partner`.
3. The monthly run generates the customer's invoice as before, one per customer team, and sets `payer_team`.
4. Collection uses the payer's Billing Profile, payment method, and wallet. Dunning goes to the payer. Central also tells the customer team's owner before a suspension.
5. Users with `billing:view` in the payer team can read the invoice. The customer still sees usage and the invoice, marked "Paid by <partner>".

Rules:

- The payer of an invoice is the payer when the invoice is generated. Central does not split a month.
- The customer can go back to "I pay" at any time. The partner can stop paying at any time. Both take effect on the next invoice.
- When a link ends, `payer` is no longer used. The customer pays from the next invoice.
- The customer can always pay an invoice of their own team, also when the partner is the payer.

The partner gets one invoice per customer with every line item. Central does not merge customer usage into the partner's own invoice.

## What ending a link does

Either side can end a link: the customer under Team, Partners, the partner under Customers, Connect with `end_partner_link`, and Central when the customer team is deleted or the partner team loses `connect_partner_id`.

| Area | Result |
|---|---|
| Console and API access | The next request from partner staff is refused. The customer team leaves their team switcher. |
| Open sessions on the customer's sites | Central asks Pilot to end the sessions of partner staff on the customer's sites. |
| SSH keys that partner staff added | Central removes them from the customer's servers. |
| Servers and sites the partner created | They stay with the customer. The customer team owns everything in it. |
| Billing | Existing invoices keep `partner_team` and `payer_team`. New invoices have neither. |
| Notification | Central sends an email to the owner of the other team. Connect reads the change with `get_partner_customers`. |

## Press migration

Press holds 276 partner teams and 1,387 customer teams that name a partner. 112 of the customer teams are `Paid By Partner`.

1. Register each active Press partner before its customers move, and keep its Press `partner_referral_code` as `partner_code`.
2. When a customer team moves to Central, the migration creates the Partner Link directly as `Active`, with an empty `role`. A Press partner has no access to a customer by default.
3. Set `payer` to `Partner` when the Press team is `Paid By Partner`. Press already recorded both approvals.
4. Central does not ask the customer again. The customer can change the role and the payer afterward.
5. The 87 Press child teams become ordinary teams. Their owner decides whether to keep them or move the servers into a Project.

## Build order

The steps go from the simplest to the hardest. Each step works without the next one.

| Step | Central | Connect |
|---|---|---|
| 1. Registration and code | `Team.connect_partner_id`, `Team.partner_code`, Partner Registration, the landing page, `register_partner`, `get_partner_registration` | Already calls both. Store the partner code on Partner. Replace the derived `referral_code`. |
| 2. Link and attribution | Partner Link with `status`, `reference`; the Add partner page with the code only; `get_partner_customers` without `sites`; `Invoice.partner_team` | Replace `request_cloud_link` and `sync_cloud_links` with the deep link and a list sync. Move the link state from Customer Project to Partner Customer. Remove the manual Approve link. Create `Own` customers. |
| 3. Access | `partner:act_on_customers`, `team:manage_partners`, the `role` field, the rules in `central/iam.py`, the team switcher, the activity log, the Partners and Customers pages, the effects of ending a link | Show the role. Call `end_partner_link` on Churned. |
| 4. Reads for Connect | `sites` and `mrr` in `get_partner_customers`; `get_partner_invoices` | Replace the demo data in `central_billing.py` and the Invoicing page. Compute the tier from Central and Press invoices together. |
| 5. Partner pays | The `payer` field, the accept action, `Invoice.payer_team`, collection, dunning, and permissions through the payer | Show who pays. |
| 6. Press migration | The import of partners and links | The import of Partner Customer rows |

Before step 5, read `central/billing/revenue/invoicing/` to confirm how an invoice gets its currency and tax. When the customer and the partner differ in currency or tax regime, the invoice must use the payer's Billing Profile. This is not verified.

## Tier

Connect owns the tier. Until Press closes, Connect reads paid invoices from both clouds, stores one row per source and invoice, and computes the tier from their sum. The basis is paid invoices, after discount, before tax. When Press closes, Connect removes that source.

## Open decisions

- The Invoicing page mock in Connect subtracts a tier discount from the partner's bill. Central has no partner discount. Decide if one is necessary.
- `get_partner_invoices` includes the invoices of the partner's own team. Decide if they count toward the tier.

## Not in this contract

- A spending limit or budget for a customer that the partner pays for.
- Commission, referral rewards, and promotional credits.
- Local payment partners (Mpesa). They stay on Press.
- Leads, certificates, audits, and partner onboarding data. They move from Press and frappe.io to Connect and never reach Central.
- A push from Central to Connect. If Central must push later, Central signs the request and Connect checks it against Central's JWKS.

## Changes to this contract

This document is the contract. There is no version field. To change the contract:

1. Change this document in a pull request to Central.
2. Get a review from the Connect developers.
3. Deploy Central before Connect starts to use a new endpoint or argument.
