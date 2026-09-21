# Proxy routes

## Purpose

A `Site Domain` record routes one domain to the IPv6 address of a VM through the regional Atlas HTTP proxy. Central owns the record. The proxy holds the route map. See the proxy [control daemon API](../../../../../atlas/services/http-proxy/docs/control-daemon.md) for the map rules.

## Configuration

| Setting | Location | Example |
|---|---|---|
| Wildcard domain | `Central Settings.wildcard_domain` | `frappe.dev` |
| Region ID | `Region.atlas_region_id` | `42` |
| Signing key | [Central SSO Settings](../central_sso_settings/SPEC.md), with **Initialize Atlas Signing Key** | `central:<hash>` |

Central reaches each regional service at `<service>.<region>.<wildcard domain>`, such as `https://proxy.in-mumbai.frappe.dev`. `Region.get_service_url(service, region)` builds the URL for `proxy`, `atlas`, and `cargo`. `Region.get_proxy_client(region)` returns a `ProxyClient` with a fresh proxy token from `central.sso.mint_proxy_token`. The token uses the Atlas signing key, the audience `atlas-proxy:<region ID>`, and the scope `site:* domain:*`.

## Site or custom domain

`Site Domain.route_type` comes from the domain. Central does not accept it as input.

| Domain | Route type | Proxy key |
|---|---|---|
| `erp.in-mumbai.frappe.dev` | Site | `erp`, in `/v1/sites` |
| `www.example.com` | Domain | `www.example.com`, in `/v1/domains` |

Central refuses the regional zone itself, a name 2 or more labels below the zone, a wildcard, and the reserved site names `proxy`, `proxy-*`, `atlas`, and `cargo`. The server must belong to the team and the region of the record.

## Routed names

The regional proxy answers a `site-*` or `*-vm-*` name below the zone from the label alone. It reads the mesh address out of the base-36 token of the label before it reads its site map, and it refuses a map entry for such a name with HTTP 409.

`Region.get_vm_admin_host` and `Region.get_vm_site_host` build the 2 routed names of one server from `Asset.ipv6_address`. Example: `admin-vm-1z141z4.par-2.frappe.dev` and `site-1z141z4.par-2.frappe.dev`.

- Central keeps no record for a routed name and makes no proxy call for it. `register_domain` returns success, because the name is live already.
- Central refuses a routed name that belongs to a different server. No record can bring that name to this server.
- A delete of a record that holds a routed name makes no proxy call.

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

## Pilot registration

A Pilot uses these endpoints from its `bench-domain-provider`. Each endpoint authenticates with `X-Pilot-Token`. The route always targets the server of the Pilot credential, never a server from the request.

| Endpoint | Method | Pilot verb |
|---|---|---|
| `central.api.pilot.domain_records?domain=` | GET | `generate-dns-records` |
| `central.api.pilot.register_domain` | POST | `register` |
| `central.api.pilot.deregister_domain` | POST | `deregister` |

A site needs no DNS records. `register_domain` creates the route when no other server holds the name. For a routed name of the Pilot server, it returns success and creates nothing.

A custom domain needs verification before Central creates a record:

1. `domain_records` returns a CNAME from the domain to `proxy.<region>.<wildcard domain>`, and a TXT record `_frappe-verification.<domain>` with a random token.
2. Central keeps the token in the cache for 24 hours, at `site-domain||<domain>||<pilot credential ID>||verification-token`. A repeat call returns the same token.
3. `register_domain` looks up the TXT record, and the CNAME when the domain is not an apex. An apex cannot hold a CNAME, so Central does not check it. When a record does not match, Central returns HTTP 409 and creates no record.
4. When the records match, Central creates the record and sends the route. The call returns only when the route is Active. When the proxy fails, Central keeps no record, so the Pilot can retry.

`deregister_domain` deletes the record and the route. It refuses a route of another server and accepts a route that does not exist.

## Permissions

A team member with `server:view` can read the records of that team. Only a System Manager creates, retries, or deletes a record.
