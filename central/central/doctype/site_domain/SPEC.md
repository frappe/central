# Proxy routes

## Purpose

A `Site Domain` record routes one domain to the IPv6 address of a VM through the regional Atlas HTTP proxy. Central owns the record. The proxy holds the route map. See the proxy [control daemon API](../../../../../atlas/services/http-proxy/docs/control-daemon.md) for the map rules.

## Configuration

| Setting | Location | Example |
|---|---|---|
| Wildcard domain | `Central Settings.wildcard_domain` | `frappe.dev` |
| Region ID | `Atlas Instance.atlas_region_id` | `42` |
| Signing key | [Central SSO Settings](../central_sso_settings/SPEC.md), with **Initialize Atlas Signing Key** | `central:<hash>` |

Central reaches each regional service at `<service>.<region>.<wildcard domain>`, such as `https://proxy.in-mumbai.frappe.dev`. `Region.get_service_url(service, region)` builds the URL for `proxy`, `atlas`, and `cargo`. `Region.get_proxy_client(region)` returns a `ProxyClient` with a fresh proxy token from `central.sso.mint_proxy_token`. The token uses the Atlas signing key, the audience `atlas-proxy:<region ID>`, and the scope `site:* domain:*`.

## Site or custom domain

`Site Domain.route_type` comes from the domain. Central does not accept it as input.

| Domain | Route type | Proxy key |
|---|---|---|
| `erp.in-mumbai.frappe.dev` | Site | `erp`, in `/v1/sites` |
| `www.example.com` | Domain | `www.example.com`, in `/v1/domains` |

Central refuses the regional zone itself, a name 2 or more labels below the zone, a wildcard, and the reserved site names `proxy`, `proxy-*`, `atlas`, and `cargo`. The server must belong to the team and the region of the record.

## Operation

```text
insert --> after_insert job --> apply() --> PATCH route --> Active
                                   |
                                   '--> error --> Failed + failure_reason
Failed or lost Pending --> retry_failed (every 5 minutes, while attempts < 5) --> apply()
delete --> on_trash --> DELETE route --> record deleted
                           '--> error --> delete refused
```

- `apply()` reads the current `Asset.ipv6_address`, sends it, and stores it in `ipv6_address`. A success resets `attempts` to 0.
- The desk **Retry** button resets `attempts` and runs `apply()` again. It shows for a record that is not Active.
- A PATCH and a DELETE are safe to repeat, so a retry never needs cleanup.
- A delete fails when the proxy call fails. The record stays, so the route and the record cannot drift apart. Fix the cause and delete again.

## Permissions

A team member with `server:view` can read the records of that team. Only a System Manager creates, retries, or deletes a record.
