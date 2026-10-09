# Integrations with Atlas, Pilot, and Cargo

## Purpose

Central owns identity, Team capabilities, catalog policy, and billing. Atlas owns regional images, virtual machines, placement, and proxy routing. Pilot owns the benches and sites inside a server. Cargo builds the prepared images.

Central reaches each service through `central/integrations/`. Team authorization follows [IAM](IAM.md) and [Capabilities](../CAPABILITIES.md).

## Who owns what?

```text
Customer -> Central Team -> trial VM -> Pilot site
                |
Central: permissions, product choice, operation record, domain claim
                |
                +-> Atlas: VM creation, placement, power, sleep, host migration
                +-> Regional proxy: applied hostname routes
                +-> Pilot: site/admin rename, site configuration, certificates
                +-> Cargo: regional storage lifecycle and bucket operations

Atlas/Cargo report -> central.api.state_delivery.receive -> scoped state update
Central repair scan -> same state update
```

Central does not issue certificates, edit guest nginx, transfer VM disks, or select Metal hosts. All remote calls stay under `central/integrations/`.

Central owns authorization and the customer-visible result. It verifies that a requested domain belongs to the caller before it changes a regional route.

The customer Team owns the trial before and after a paid upgrade. A Team can own several VMs with the same network tenant ID.

## Regional authentication

Region stores the direct regional URL and numeric region ID, alongside its geography and display identity. Central signs a short-lived token for that region. Each request carries the Team tenant ID in `X-Tenant-ID`. Atlas verifies the token and enforces the tenant boundary.

System images form a shared regional catalog. The tenant header identifies the authorized caller. It does not make those images Team-owned. Operator connection checks use the system tenant.

See [Regional configuration](../central/infrastructure/doctype/region/SPEC.md) for trust setup and connection checks.

## How are tenants and regional keys managed?

Allocate unique, immutable, unsigned 32-bit Team tenant IDs through a persistent sequence. Reserve tenant zero for infrastructure. Preserve verified existing mappings and reject ambiguous data.

Do not reuse committed tenant IDs. Backfill before you enforce constraints. Test concurrent allocation and the actual migration order.

Store regional VM references with their Region. A VM name alone is not globally unique. Do not change existing Central resource IDs without need.

Central owns image offering presentation and matching tags. Central fetches regional System image builds from Atlas on demand. See [Image offerings](../central/infrastructure/doctype/image_offering/SPEC.md).

The Atlas image response exposes tags, architecture, availability, and disk size. Declare and test software resource requirements at the image builder. Do not duplicate regional builds or copy runtime metadata into Central by hand.

A matching size permits a warm start but does not guarantee that the selected host has the warm artifact. Cold startup must stay usable.

Regional tokens use Ed25519 keys with a `central:` key identifier. Atlas tokens carry `iss=central`, `aud=atlas-admin:<region ID>`, `scope=*`, and `tenant=*`. See [SSO](SSO.md) for every token type.

The client supplies `X-Tenant-ID` from the authorized Team. Never accept a customer-supplied tenant header as authority.

Publish keys before use and verify consumer acceptance. Serialize first-use key creation. Restrict key changes to operators.

A public key-set read must not rotate keys. Keep private keys and bootstrap credentials out of customer responses.

Region is the single owner of regional identity and connection configuration.

## Image contract

Central fetches available System images when the customer selects a region and Image Offering. An offering contains presentation fields, allowed flows, and required tags. It does not store regional builds.

Atlas must return the following fields with each build:

| Field | Central use |
|---|---|
| ID, title, tags, and architecture | Identify and describe the selected build. |
| Enabled flag and availability state | Show only usable builds. |
| Root filesystem size in MiB | Reject plans whose disk cannot hold the image. |

Cargo's current Pilot image contains `default-bench` and `site.local`. Server and signup flows use that image layout. Ubuntu uses a base image. SSH keys are optional. See [Image Offering](../central/infrastructure/doctype/image_offering/SPEC.md) for selectors and pagination.

Server creation has two customer options, stored on `Virtual Machine` as `has_public_ipv6` and `is_firewall_enabled`. Central sends an option to Atlas only when the customer selects it:

| Option | Atlas create field |
| --- | --- |
| Public IPv6 | `public_ipv6: "auto"` |
| Firewall | `firewall.enabled: true` with the rules below |

The firewall allows all inbound traffic from the mesh prefix `fdaa::/16`, because an enabled Atlas firewall also filters mesh traffic and the regional gateway reaches a machine over the mesh. It also allows inbound ICMP, inbound TCP ports 22, 80, and 443, and all outbound traffic. Without the option, Central sends `firewall.enabled: false`, which permits all traffic.

Atlas reports the guest public IPv6 as a `/128` prefix. Central stores the address without the prefix length in `public_ipv6`, and stores `public_ipv4` as reported. The overview shows `ssh root@<address>` for every image and uses the IPv6 address first. See [Team SSH Key](../central/infrastructure/doctype/team_ssh_key/SPEC.md) for selected keys and rotation.

A member with `server:console` can open the web console of a running server of any image. Central asks Atlas for a single-use console token in `ssh` mode through `POST /virtual-machines/{id}/actions/console-token`. If Atlas definitely refuses the `ssh` token, Central asks for a `tty` token instead, because every guest has a serial console. Central does not fall back when it cannot authenticate, reach Atlas, or confirm the result, or when the VM does not exist. Central returns `<region base URL>/vm_console#token=<token>`. The dashboard asks for a new token each time a member opens the console from the overview or the server actions, because Atlas spends the token on first use. It opens the Atlas URL in one popup window per server, so a second request replaces the session in that window. The token expires after 30 seconds and stays in the URL fragment, so the browser does not send it to a server.

## Server operation contract

Central stores each authorized operation in Resource Action before dispatch. Atlas receives one create or power request. Central saves the accepted VM identity before local finalization. A lost mutation response remains uncertain and must not trigger another remote mutation.

Scoped regional reads confirm VM state and repair interrupted local finalization. A failed read does not prove deletion. A scoped not-found response can confirm deletion and trigger local credential and billing cleanup.

Central builds the automatic management address itself. The regional proxy decodes a VM's mesh address from its hostname label, so Central encodes the same label from the observed mesh address and the region's proxy domain. The tenant API does not publish the regional zone, so an operator sets `proxy_domain` on [Region](../central/infrastructure/doctype/region/SPEC.md). A management address alone does not prove Pilot readiness. Pilot creation also receives credential-bound `pilot-central` metadata and `pilot-common-config` metadata with the telemetry settings when the region has a telemetry host. When Central Settings has a **Common Site Config**, every server also gets it as `pilot-common-site-config`, which Pilot merges into `sites/common_site_config.json` at bootstrap, such as an app's relay URL. The customer can read it, so it never holds a secret. The region's host refuses guest metadata with more than 64 entries, a key longer than 128 bytes, or a value longer than 1024 bytes. `AtlasClient.create_vm` refuses the same metadata before it calls Atlas, because Atlas saves a draft machine before the host rejects the request.

See [Resource Action](../central/infrastructure/doctype/resource_action/SPEC.md) for states, authorization, recovery, accepted quotes, and customer responses.

## How does a site prove its team to an outside service?

An app on a site, such as Raven, asks Central for a token through Pilot's Central proxy: `central.api.pilot.get_team_identity_token(audience)`. Pilot's credential names the team, so a site cannot get a token for another team.

`get_team_identity_token` returns a token that Central signs with its Pilot key. The token is valid for 5 minutes. Central stores no account and no secret for the outside service.

| Claim | Value |
|---|---|
| `iss` | Central's issuer URL |
| `aud` | The service URL that the site gave as `audience` |
| `sub` | The team, such as `TEAM-00042` |
| `team_name` | The team's name |
| `scope` | `team-identity` |
| `hosts` | The hostnames of the team's sites on the Pilot's server: each site's own address and its active Site Domain records. Empty when the credential has no server. |

The service gets Central's public keys from `central.api.jwks.get_jwks` and verifies the signature, `iss`, `aud`, `exp` and `scope`. Then the service decides what access the team gets, for example a team account and its API keys. The Pilot credential names the team and its server, so a site cannot get a token for another team or for a hostname that the team does not serve. A service uses `hosts` to accept a site's hostname as the team's. A Pilot refuses a `team-identity` token as a login token.

## How does the trial flow work?

1. Authenticate the customer and resolve the Team.
2. Validate the trial limit, approved image, size, region, and existing eligibility.
3. Persist the request and its unique customer request key.
4. Issue and store a VM-specific Pilot credential and audience.
5. Call Atlas with the image, size, sleep policy, and `pilot-central` metadata.
6. Store the returned VM reference and automatic site and admin names.
7. Observe the VM and verify bounded Pilot and site readiness.
8. Record the site already present in the prepared image.
9. Return the site login through the dashboard.

Metadata contains `central_endpoint`, `central_auth_token`, `jwks_url`, `jwks_audience_id`, and `initial_jwks_cache`. Do not put customer credentials into the shared image.

A VM running event can finish VM provisioning. It cannot prove that the site is ready for login. Keep VM state and site readiness separate.

Persist the request before remote work and enqueue after commit. A recovery sweep finds requests lost between commit and enqueue.

Central request deduplication does not make Atlas creation safe to repeat after a network timeout. Keep uncertain acceptance as an explicit state. Resolve an uncertain create through a verified lookup or operator recovery. Do not send a second create automatically without an upstream idempotency contract.

Bind credentials to the known VM. Revoke unused credentials after confirmed provisioning failure and bound credentials after confirmed deletion.

Do not disable eligibility, Team authorization, size validation, or trial-abuse checks.

## How do server creation and lifecycle work?

Trial, Pilot-server, and plain-Ubuntu creation use the same authorized Atlas adapter. Each flow has an explicit readiness rule.

| Resource | Configuration | Completion |
|---|---|---|
| Trial | Prepared Pilot image, one existing site, metadata credential, approved idle timeout. | VM accepted, Pilot ready, site reachable, and site login succeeds. |
| Pilot server | Cargo Pilot image with its prepared bench and site, plus metadata credential. | VM is ready and Central can open the correct Pilot admin. |
| Plain Ubuntu | Approved Ubuntu image, allowed size, hostname, and SSH keys. | Atlas confirms the requested running state and the agreed access configuration. No Pilot or Site record is required. |

Show Open Pilot only for a Pilot-managed resource. A plain Ubuntu VM must not fail because it has no Pilot process or site.

Do not expose privileged VM creation or system tenant zero to customers.

Idle sleep is a trial policy. Ordinary Pilot servers and plain Ubuntu servers have no idle sleep unless their product requires it.

Record each operation separately from observed state and show a useful error on failure.

An explicit stop sets the desired state to stopped. It is different from idle sleep, where desired state stays running. Customer traffic must not undo an explicit stop.

A repeated running event cannot prove that a restart finished. Resource Action waits for one observed state change away from Running before Running can complete a restart. The region publishes no restart counter. An upstream restart-completion contract is open work. Do not mark false success.

Opening Pilot uses a short-lived audience-bound token and the automatic admin name. Deny another Team's access.

Pilot links back to its server in the console with `/dashboard/servers?pilot=<jwks_audience_id>&action=<action>`. The action is `overview` or `resize`; any other value opens the overview. A resize link opens the dialog only when the server can take a change and the user may resize it. The server list returns each server's active audience as `pilot_audience`, and the console matches the link against it. When the active Team does not hold that server, the console shows the server list and a message.

Display supported network and SSH information for a plain Ubuntu server. Do not imply that a private mesh address is publicly reachable.

Delete only after the customer confirms the action. Confirm remote absence, revoke any Pilot credential, and preserve existing billing cancellation behavior.

## What does creation depend on?

The current creation flow requires the Atlas VM API and automatic management hostname. Staging also needs current schema, key trust, a healthy host, available images, and wildcard DNS.

Central receives signed state reports at `central.api.state_delivery.receive`. See [Inbound webhooks](WEBHOOKS.md) for the contract. State reports supplement repair reads. They do not replace durable intent, and a callback is never the only recovery path. Resize uses the Atlas resize API, which moves a VM to another host when its host cannot fit the new size.

Central verifies domain ownership and owns the proxy route through [Site Domain](../central/infrastructure/doctype/site_domain/SPEC.md). The regional proxy terminates TLS for a regional name. For a custom domain, the proxy passes TLS to the VM, and Pilot holds the certificate. Central does not issue or store certificates.

## How does state delivery work?

Atlas uses Framework's Webhook DocType to send reports. Do not rebuild an Atlas event service or a generic message platform.

Atlas and Cargo both deliver to `central.api.state_delivery.receive`. `X-FC-Source` selects the handler. [Inbound webhooks](WEBHOOKS.md) is the contract.

### Atlas sender

Configure a Webhook on Virtual Machine State with `on_update`. Verify that it covers insertion and later saves in the deployed Framework revision.

The payload carries the event, the VM ID, the observed status, and `observed_at`. Do not serialize an entire document.

The state writer saves on each host report, even when the status is unchanged. Use a tested condition for first observation or status change to avoid continuous duplicate callbacks. Do not assume that editing a Webhook filters unchanged values.

The state row has no tenant, desired state, operation ID, or site readiness. Central resolves the Team through its stored Region and VM mapping.

A callback can arrive before Central stores the create response. Central drops it as `unknown server`, and a repair read records the state later. Do not create a Team or resource from untrusted callback fields. The callback must not assign a machine to a customer based on its name.

### Verification and ordering

Central verifies `X-Frappe-Webhook-Signature` with base64 HMAC-SHA256 over the exact raw request body. Each region has its own secret for each sender. A region identifier selects a candidate secret. It becomes trusted only after signature verification.

Central validates the source, fields, status, and resource mapping. It rejects unknown senders and bad signatures uniformly.

Central orders Atlas reports by the region's `observed_at`, stored as `Virtual Machine.last_reported_at`. It ignores a report that is not newer. A signature authenticates the body but does not prevent replay. Monotonic ordering prevents state regression.

Central does not persist a receipt and does not deduplicate by payload digest. A queued job holds the accepted report.

Do not run provisioning, billing, or remote calls in the HTTP receiver. Do not put bearer tokens, passwords, or private keys in payloads or delivery logs.

### Delivery limits and recovery

Framework queues after commit and records configured delivery retries. A process can still fail between commit and enqueue. Retries can also be exhausted.

Verify sender workers, scheduler, retry configuration, and Webhook Request Log on staging. A supported DocType is not proof of active delivery.

Webhooks give the normal prompt state update. A paginated scan of known Region and tenant assignments (`central.integrations.servers.reconcile`, every 10 minutes) repairs missed observations.

Use bounded detail checks for active operations and deletion. Do not poll every guest or replace the webhook with a high-frequency fleet loop.

Atlas deletes the Virtual Machine State row through `frappe.db.delete`. That path does not produce a document deletion webhook. Central confirms VM deletion through the correctly scoped Atlas API.

A scoped `404` is also Atlas's response for another tenant's resource. Check the stored Region and tenant before you mark a known resource absent.

Fleet reads, detail reads, and webhook reports share one writer and freshness policy. Keep source observation time separate from local fetch time. An older callback or delayed read must not undo a newer result.

Follow all pages. An incomplete scan, timeout, or server error cannot prove deletion.

### Sleep

A state callback can report stopped when a VM sleeps. It does not carry the desired state.

Read Atlas detail when that difference matters. Do not mark sleep as customer shutdown, cancel a subscription, or report a failed deployment from the callback alone.

Routine synchronization must not call the guest. Signup readiness and user-requested actions may contact Pilot with bounded retries.

## How does Central register Cargo?

Central registers each region's Cargo after a health check. `cargo_connection.register_cargo` calls `CargoClient.configure_webhooks`, which sends Central's receiver URL and a fresh secret. Central stores the secret in `Region.cargo_webhook_secret` and sets `cargo_status` to `Registered`. **Enroll Cargo** on the Region form runs this on demand. `register_pending_cargo` retries Draft regions every 10 minutes.

Cargo reports `service`, `status`, and `service_endpoint`. Central records availability in Service Detail. Do not label a service healthy from a provisioning event.

## How do rename, routes, and TLS work?

Central calls the Pilot Admin API for renames.

| Operation | Pilot endpoint |
|---|---|
| Rename site | `POST /api/v1/sites/<name>/actions/rename` with `new_name` and `keep_old_hostname`. |
| Rename admin domain | `POST /api/v1/settings/admin-domain` with `domain` and `tls`. |

Central stores the returned task ID. An accepted response is not completion. Central keeps the stable Site identity while the Pilot site name changes. Preserve an automatic management alias for recovery.

A Pilot registers its site and custom-domain routes through `central.api.pilot.register_domain` and removes them through `deregister_domain`. Central verifies DNS ownership and applies the proxy route through [Site Domain](../central/infrastructure/doctype/site_domain/SPEC.md).

| Name | Route owner | TLS owner |
|---|---|---|
| Automatic VM name | Proxy computes the VM address. No map write. | Proxy regional wildcard certificate. |
| Friendly regional name | Proxy site map. | Proxy regional wildcard certificate. |
| Customer domain | Proxy domain map to the VM. | Pilot on the VM. |

Atlas provisions the regional proxy and its wildcard certificate. The separate proxy control API applies map changes. Do not give a customer VM an unrestricted regional proxy token.

Wildcard or shared-proxy DNS resolution alone does not prove customer ownership. A domain-specific ownership check is required before a route can move between Teams.

The proxy forwards customer HTTPS as TLS with PROXY protocol v2 to VM port 443. Certificates and renewal stay in Pilot. Central stores the domain record, the operation result, and useful failure information.

## Validation

Run the shared contract tests before deployment. Complete the live journeys in [Staging validation](STAGING_VALIDATION.md) against the actual staging revisions. Mocked responses do not prove VM startup, Pilot login, SSH access, or webhook delivery.
