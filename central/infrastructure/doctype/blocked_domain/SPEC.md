# Blocked domains

## Purpose

Central reserves infrastructure names before a customer assigns a site name or domain. A `Blocked Domain` record defines one reservation. Only a System Manager can read or change these records.

## Configuration

Open **Blocked Domain** in Desk. Set these fields:

| Field | Meaning | Example |
|---|---|---|
| Name | The name relative to the parent domain | `proxy-` |
| Parent Domain | The domain that contains the reserved name | `in-mumbai.frappe.dev` |
| Match Mode | `Exact` or `Prefix` | `Prefix` |
| Enabled | Whether Central enforces the reservation | On |

An exact reservation for `proxy` blocks `proxy.in-mumbai.frappe.dev`. It permits `proxy-01.in-mumbai.frappe.dev`. A prefix reservation for `proxy-` blocks names such as `proxy-01.in-mumbai.frappe.dev`. These reservations permit the same names below other parent domains.

Names can contain multiple labels. For example, `api.central` with parent `example.com` reserves `api.central.example.com`. Central compares names without case differences or trailing dots. Enter a bare parent domain without a wildcard, URL, or port. For a regional wildcard zone, enter its parent domain without `*.`.

Central creates these defaults in each configured service zone:

| Name | Match mode |
|---|---|
| Common service and account names, such as `admin`, `api`, `login`, `mail`, `root`, `support`, `wireguard`, and `www` | Exact |
| `proxy-`, `wireguard-`, `s3-svc`, `s3-admin-svc`, `cargo-pilot`, `central` | Prefix |

The [default list](defaults.json) includes common service and account names from this [reserved-name list](https://gist.github.com/anburocky3/9bc248a56b377178e5205dcd9ebbcc28). These names use exact matches, so `support-team` remains available.

The `after_install` and `after_migrate` hooks add missing defaults in each regional service zone and each Region's proxy domain. A new Region or proxy domain receives the defaults. A change to the wildcard domain seeds the configured zones. Existing reservations keep their match mode and Enabled value. A deleted default returns on the next migration. Disable a reservation to permit its names.

## Enforcement

Central checks trial-name availability in every active trial zone. It checks queued creation requests against their selected region. Site validation checks new site names and changes to the chosen subdomain. The Site rename hook checks the new name. A delayed rename checks the reservation again before it calls Pilot and records a refusal on the Site.

Site Domain validation checks new assignments and changes to the domain, server, or team. Pilot DNS instructions and new domain registrations use the same matcher. These checks run on the server, including requests that bypass the console.

A match raises a validation error that identifies the reserved domain and asks the customer to choose another name. A change to an unrelated field on an existing assignment remains possible.

## Review

Select **Find conflicting assignments** on a saved, enabled reservation. The result links to matching Site Domain records, Sites, and pending creation requests. Review each assignment with its owning team before you change it.

A reservation does not delete an existing assignment or proxy route. Existing routes can still receive address updates, register again for the same server, and be removed. Atlas infrastructure provisioning and route restoration use the proxy API without this customer validation.

## Validation

Run the focused checks on the isolated test site:

```bash
pilot frappe --site test.local run-tests --app central --module central.tests.test_blocked_domain
pilot frappe --site test.local run-tests --app central --module central.tests.test_site_domain
```
