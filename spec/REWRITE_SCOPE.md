# Central baseline scope

## Purpose

This document states what the v0.2 baseline covers, who owns each part, and the contracts between Central, Atlas, Pilot, and Cargo. [Delivery](DELIVERY.md) lists the open work. [Validation](LOCAL_ENVIRONMENT.md) defines the evidence required.

Follow [CLAUDE.md](../CLAUDE.md), [agent tooling](../llm/README.md), and [review rules](../.greptile/rules.md). Do not use `frappe-app-dev`.

## What does the baseline cover?

| Area | Limit |
|---|---|
| Customer identity | Each signup customer has a Central Team and an immutable, nonzero tenant ID. |
| Trial signup | One trial site per sleeping VM from one approved, prepared Pilot image, through site login. |
| Pilot server | Create a server from the approved Pilot image and open its Pilot admin. |
| Ubuntu server | Create a plain Ubuntu VM with the requested approved size and SSH keys. Pilot is not required. |
| Server lifecycle | Create, read, start, stop, restart, resize, snapshot, console, and delete. Show supported controls and confirmed results. |
| Regional integration | Region holds the Atlas, proxy, and Cargo connection for each region. |
| Bootstrap and login | Metadata credential delivery, automatic site and admin names, site discovery, and login. |
| State updates | Signed Atlas and Cargo reports at one receiver, bounded operation checks, and a repair scan. |
| Cargo | Central registers each region's Cargo and records service availability. |
| Rename and domains | Central asks Pilot to rename the trial site and the admin domain. A Pilot registers site and custom-domain routes through Central. |
| Cleanup | Confirm VM deletion, revoke credentials, and remove owned routes safely. |
| Interface | The dashboard and Desk show progress, error, stale, and retry states. |
| Data | Patches cover required changes to existing data. |
| Billing | Existing eligibility and resource references are preserved. Only necessary integration calls change. |

Keep `Virtual Machine` as Central's persisted server record. Keep its commercial identity and subscription links.

Use existing provisioning and action records where they fit. Add only the state and remote references needed for correctness.

## Which external sources does Central rely on?

These references describe source code. They do not prove that a deployed service runs that revision or has the required configuration.

| Source | Behavior |
|---|---|
| [Atlas state writer](../../atlas/atlas/vm/core/vm_state.py) | Saves Virtual Machine State documents and commits each write. |
| [Atlas state schema](../../atlas/atlas/vm/doctype/virtual_machine_state/virtual_machine_state.json) | Holds VM ID, observed status, and synchronization time. |
| [Framework webhook hooks](../../frappe/frappe/integrations/doctype/webhook/__init__.py) | Queues supported document events after commit. |
| [Framework webhook delivery](../../frappe/frappe/integrations/doctype/webhook/webhook.py) | Signs JSON, records delivery, and supports configured retries. |
| [Proxy data plane](../../atlas/docs/networking/http-proxy/openresty.md) | Regional wildcard TLS terminates at the proxy. Customer-domain TLS terminates on the VM. |

Sibling links assume the standard bench layout. Use the named checkout when you review from a separate worktree.

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

## Foundation

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

Display supported network and SSH information for a plain Ubuntu server. Do not imply that a private mesh address is publicly reachable.

Delete only after the customer confirms the action. Confirm remote absence, revoke any Pilot credential, and preserve existing billing cancellation behavior.

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

Central does not persist a receipt and does not deduplicate by payload digest. A queued job holds the accepted report. These gaps are listed in [Delivery](DELIVERY.md).

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

Cargo reports `service`, `status`, and `service_endpoint`. Central records availability in Service Detail. Do not label a service healthy from a provisioning event. Live health reporting and new service ordering are later work.

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

## Patches and cutover

A staging deployment permits a maintenance window and coordinated service updates. It does not permit silent data loss.

Add patches for required fields, data backfills, and references. Keep indexes and constraints in controller hooks, with valid migration ordering.

Back up the database and private files before cutover. Pause affected mutations and workers. Validate records and regional calls before you resume them.

Remove obsolete regional mutation paths when their replacements land. Do not leave a dashboard control that calls a removed endpoint or reports false success.

## What is later work?

| Area | Later work |
|---|---|
| API surface | Reusable typed core, OpenAPI, and generated Central clients. |
| Images | Private machine image selection and additional application bundles. |
| Products | Multi-site products. |
| Services | New service ordering and live service health. |
| Partners | Partner flows. |

Keep billing calculations and its public API outside the rewrite. Review every necessary billing integration change with focused and full billing tests.
