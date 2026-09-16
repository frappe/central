# Central v0.2 staging integration

## Purpose

Deliver the smallest complete Central, Atlas, and Pilot flow on staging by Friday, September 18, 2026. This is a target, not a claim that the dependencies are ready.

The Friday milestone takes priority over the wider rewrite. [Delivery](DELIVERY.md) defines the PRs and acceptance gates. [Validation](LOCAL_ENVIRONMENT.md) defines the evidence required.

Follow [CLAUDE.md](../CLAUDE.md), [agent tooling](../llm/README.md), and [review rules](../.greptile/rules.md). Do not use `frappe-app-dev`.

## Scope for Friday

| Include | Limit |
|---|---|
| Customer identity | Each signup customer has a Central Team and an immutable, nonzero tenant ID. |
| Trial signup | One trial site per sleeping VM from one approved, prepared Pilot image, through site login. |
| Pilot server | Create a server from the approved Pilot image and open its Pilot admin. |
| Ubuntu server | Create a plain Ubuntu VM with the requested approved size and SSH keys. Do not require Pilot. |
| Server lifecycle | Create, read, start, stop, restart, and delete. Show supported controls and confirmed results. |
| Regional integration | One provisioned staging region with working Atlas, proxy, and Cargo infrastructure. |
| Bootstrap and login | Metadata credential delivery, automatic site/admin names, site discovery, and login. |
| State updates | Signed Framework webhooks, a durable receiver, bounded operation checks, and a repair scan. |
| Cargo | Existing regional infrastructure and available images are prerequisites. Central Cargo registration and service ordering are not Friday work. |
| Cleanup | Confirm VM deletion, revoke credentials, and remove owned routes safely. |
| Interface | Wire these flows into the existing dashboard and Desk. Show progress, error, stale, and retry states. |
| Data | Add patches for required changes to existing staging data. |
| Billing | Preserve existing eligibility and resource references. Change only necessary integration calls. |

Do not make rename, custom domains, Cargo registration, resize, migration, snapshots, or console streaming dependencies for Friday.

Do not make a new API framework, generated Central client, catalog redesign, broad rename, or general code cleanup a dependency for Friday.

Keep `Asset` as the persisted server record for this milestone. Keep its existing commercial identity and subscription links. Rename it to `Server` after staging works.

Use existing provisioning and action records where they fit. Add only the state, remote references, and receipt data needed for correctness.

## Confirmed source baseline

The latest fetched revisions are Atlas `7eadeda7`, Pilot `228c46fa`, and Cargo `2b7845d`. The reviewed Framework checkout is `3f96501d86`.

The requested `pilot admin upgrade` completed. Pilot was already current. Its dependency setup and upgrade patches ran. Local tracked source edits remained unchanged.

These checks inspected source code. They do not prove that the staging services run these revisions or have the required configuration.

| Source | Confirmed behavior |
|---|---|
| [Atlas state writer](../../atlas/atlas/vm/core/vm_state.py) | Saves Virtual Machine State documents and commits each write. |
| [Atlas state schema](../../atlas/atlas/vm/doctype/virtual_machine_state/virtual_machine_state.json) | Holds VM ID, observed status, and synchronization time. |
| [Framework webhook hooks](../../frappe/frappe/integrations/doctype/webhook/__init__.py) | Queues supported document events after commit. |
| [Framework webhook delivery](../../frappe/frappe/integrations/doctype/webhook/webhook.py) | Signs JSON, records delivery, and supports configured retries in this revision. |
| [Pilot site routes](https://github.com/frappe/pilot/blob/228c46fa/admin/backend/api/v1/sites/core.py) | Site rename returns an asynchronous task. |
| [Pilot settings routes](https://github.com/frappe/pilot/blob/228c46fa/admin/backend/api/v1/settings/__init__.py) | Admin-domain rename returns an asynchronous task. |
| [Pilot domain routes](https://github.com/frappe/pilot/blob/228c46fa/admin/backend/api/v1/sites/domains.py) | DNS guidance, domain attachment, removal, and TLS operations already exist. |
| [Proxy data plane](../../atlas/services/http-proxy/docs/openresty.md) | Regional wildcard TLS terminates at the proxy. Customer-domain TLS terminates on the VM. |
| [Cargo cluster controller](../../cargo/cargo/object_storage/doctype/object_storage_cluster/object_storage_cluster.py) | Creates an Object Storage Cluster Framework webhook for Active and Failed states. |

Sibling links assume the standard bench layout. Use the named checkout when reviewing from a separate worktree.

## Ownership

```text
Customer -> Central Team -> trial VM -> Pilot site
                |
Central: permissions, product choice, operation record, domain claim
                |
                +-> Atlas: VM creation, placement, power, sleep, host migration
                +-> Regional proxy: applied hostname routes
                +-> Pilot: site/admin rename, site configuration, certificates
                +-> Cargo: regional storage lifecycle and bucket operations

Atlas/Cargo Framework Webhook -> Central receipt -> scoped state update
Central repair scan          -> same state update
```

Central does not issue certificates, edit guest nginx, transfer VM disks, or select Metal hosts. All remote calls stay under `central/integrations/`.

Central owns authorization and the customer-visible result. It must verify that a requested domain belongs to the caller before allowing regional route changes.

The customer Team owns the trial before and after a paid upgrade. A Team can own several VMs with the same network tenant ID.

## Minimum foundation

Allocate unique, immutable, unsigned 32-bit Team tenant IDs through a persistent sequence. Reserve tenant zero for infrastructure. Preserve verified existing mappings and reject ambiguous data.

Do not reuse committed tenant IDs. Backfill before enforcing constraints. Test concurrent allocation and the actual migration order.

Store regional VM references with their Region. A VM name alone is not globally unique. Do not change existing Central resource IDs unnecessarily.

Configure one region and two approved image profiles: Pilot and plain Ubuntu. Record supported sizes and architecture. Record the Pilot profile's prepared shape and runtime versions.

The reviewed Atlas image response lacks the prepared snapshot shape. An operator-verified image profile can supply that shape for Friday. A complete synchronized image catalog is later work.

A matching size permits a warm start but does not guarantee that the selected host has the warm artifact. Cold startup must remain usable.

Implement the signing and bootstrap path required by Atlas and Pilot. Check every consumer affected by a shared signer change before changing it. Do not break Datum or Cargo implicitly.

Use Ed25519 keys with a `central:` key identifier. Atlas tokens carry `iss=central`, `aud=atlas-admin:<region ID>`, `scope=*`, and `tenant=*`.

The client supplies `X-Tenant-ID` from the authorized Team. Never accept a customer-supplied tenant header as authority.

Publish keys before use and verify consumer acceptance. Serialize first-use key creation. Restrict key changes to operators and record the cutover.

A public key-set read must not rotate keys. Keep private keys and bootstrap credentials out of customer responses.

Keep unrelated Cargo and Datum token paths unchanged if they are not required by the milestone. A signer change must not break them indirectly.

Do not require the Atlas Instance-to-Region merge for staging. Keep one explicit configuration owner and defer structural consolidation. Add required endpoint fields and data patches only.

## Trial flow

1. Authenticate the customer and resolve the Team.
2. Validate the trial limit, approved image, size, region, and existing eligibility.
3. Persist the request and its unique customer request key.
4. Issue and store a VM-specific Pilot credential and audience.
5. Call Atlas with the image, size, sleep policy, and `pilot-central` metadata.
6. Store the returned VM reference and automatic site/admin names.
7. Observe the VM and verify bounded Pilot/site readiness.
8. Record the site already present in the prepared image.
9. Return the site login through the existing dashboard.

Metadata contains `central_endpoint`, `central_auth_token`, `jwks_url`, `jwks_audience_id`, and `initial_jwks_cache`. Do not bake customer credentials into the shared image.

A VM running event can finish VM provisioning. It cannot prove that the site is ready for login. Keep VM state and site readiness separate.

Persist the request before remote work and enqueue after commit. A recovery sweep must find requests lost between commit and enqueue.

Central request deduplication does not make Atlas creation safe to repeat after a network timeout. Keep uncertain acceptance as an explicit state.

For Friday, resolve an uncertain create through a verified lookup or operator recovery. Do not send a second create automatically without an upstream idempotency contract.

Bind credentials to the known VM. Revoke unused credentials after confirmed provisioning failure and bound credentials after confirmed deletion.

Do not silently disable eligibility, Team authorization, size validation, or trial-abuse checks to meet the deadline.

## Server creation and lifecycle

Use the same authorized Atlas adapter for trial, Pilot-server, and plain-Ubuntu creation. Each flow has an explicit readiness rule.

| Resource | Configuration | Completion |
|---|---|---|
| Trial | Prepared Pilot image, one existing site, metadata credential, approved idle timeout. | VM accepted, Pilot ready, site reachable, and site login succeeds. |
| Pilot server | Approved Pilot image and metadata credential. | VM is ready and Central can open the correct Pilot admin. |
| Plain Ubuntu | Approved Ubuntu image, allowed size, hostname, and SSH keys. | Atlas confirms the requested running state and the agreed access configuration. No Pilot or Site record is required. |

Show Open Pilot only for a Pilot-managed resource. A plain Ubuntu VM must not fail because it has no Pilot process or site.

Keep the existing server creation interface and add a clear image type choice. Do not expose privileged VM creation or system tenant zero to customers.

Keep idle sleep a trial policy for Friday. Default ordinary Pilot servers and plain Ubuntu servers to no idle sleep unless their product explicitly requires it.

Support start, stop, restart, and delete through Atlas. Record the operation separately from observed state and show a useful error on failure.

An explicit stop sets the desired state to stopped. It is different from idle sleep, where desired state remains running. Customer traffic must not undo an explicit stop.

Use current detail reads and the request contract to confirm actions. A repeated running event cannot prove that a restart finished. Verify an operation generation or another authoritative completion signal.

If the public API cannot prove restart completion, add the smallest upstream contract or report the action as accepted with an unconfirmed outcome. Do not mark false success.

Opening Pilot uses a short-lived audience-bound token and the automatic admin name. Deny another Team's access. Allow bounded readiness checks for this user-requested action.

Plain Ubuntu access must be specified for the test environment. Display supported network and SSH information. Do not imply that a private mesh address is publicly reachable.

Delete only after the customer confirms the action. Confirm remote absence, revoke any Pilot credential, and preserve existing billing cancellation behavior.

## Framework webhook design

Use Framework's Webhook DocType on the sender. Do not rebuild an Atlas event service or a generic message platform.

Use an Atlas receiver for Friday. Add the separate Cargo receiver in the next integration phase, with its own sender configuration and secret.

| Sender | Central receiver | Purpose |
|---|---|---|
| Atlas, Friday | `central.api.atlas_webhooks.virtual_machine_state` | Receive VM state observations for one configured region. |
| Cargo, after Friday | `central.api.cargo_webhooks.object_storage_cluster_webhook` | Match the endpoint already named by Cargo's storage webhook. |

These are proposed Central endpoints, not existing implemented routes. Both delegate authentication, receipt handling, and state updates to their owning integration modules.

### Atlas sender

Configure a Webhook on Virtual Machine State using `on_update`. Verify that it covers insertion and later saves in the deployed Framework revision.

The payload contains a fixed configured region identity, VM ID, observed status, and `synced_at`. Include a payload version. Do not serialize an entire document.

The state writer saves on each host report, even when the status is unchanged. Use a tested condition for first observation or status change to avoid continuous duplicate callbacks.

Prove the condition against the pinned Framework. Do not assume that editing a Webhook automatically filters unchanged values.

The state row has no tenant, desired state, operation ID, or site readiness. Resolve the Team through Central's stored Region/VM mapping.

A callback can arrive before Central stores the create response. Keep unmatched authenticated receipts for bounded retry. Do not create a Team or resource from untrusted callback fields.

Unknown remote resources require operator reconciliation. The callback must not assign a machine to a customer based on its name.

### Receipt and verification

Verify `X-Frappe-Webhook-Signature` using base64 HMAC-SHA256 over the exact raw request body. This is Framework's signature format, not the removed Atlas custom HMAC format.

Use a separate shared secret for each configured sender or region. A region identifier selects a candidate secret. It becomes trusted only after signature verification.

Validate the source, payload version, allowed fields, types, status, and resource mapping. Reject unknown senders and malformed signatures uniformly. Limit request size.

Persist an authenticated receipt before returning success. Process it asynchronously through one state-update owner. Recover receipts whose job was not enqueued or whose worker stopped.

Framework does not supply a globally unique event ID in this payload. Deduplicate by sender and payload digest, with a database uniqueness rule.

Track observation order per resource. Ignore older observations and make repeated lifecycle effects safe. Do not reject legitimate delayed retries solely because their delivery time is old.

A signature authenticates the body but does not prevent replay. Receipt deduplication and monotonic observation handling must prevent repeated effects.

Do not run provisioning, billing, or remote calls in the HTTP receiver. Do not place bearer tokens, passwords, or private keys in payloads or delivery logs.

### Delivery limits and recovery

The reviewed Framework queues after commit and records configured delivery retries. A process can still fail between commit and enqueue. Retries can also exhaust.

Verify sender workers, scheduler, retry configuration, and Webhook Request Log on staging. A supported DocType is not proof of active delivery.

Webhooks provide the normal prompt state update. Keep a low-frequency, paginated scan of known Region/tenant assignments to repair missed observations.

Use bounded detail checks for active operations and deletion. Do not poll every guest or replace the webhook with a high-frequency fleet loop.

Atlas deletes the Virtual Machine State row through `frappe.db.delete`. That path does not produce a document deletion webhook. Confirm VM deletion through the correctly scoped Atlas API.

A scoped `404` is also Atlas's response for another tenant's resource. Check the stored Region and tenant before marking a known resource absent.

Fleet reads, detail reads, and webhook receipts share one writer and freshness policy. Serialize updates per resource or reject stale writes atomically.

Keep source observation time separate from local fetch time. An older callback or delayed read must not undo a newer result.

Follow all pages. An incomplete scan, timeout, or server error cannot prove deletion. Bound retries and concurrency, and expose stale state.

### Sleep

A state callback can report stopped when a VM sleeps. It does not carry the desired state.

Read Atlas detail when that distinction matters. Do not mark sleep as customer shutdown, cancel a subscription, or report a failed deployment from the callback alone.

Check errors and pending operations before describing a stopped VM as asleep. Keep unknown state explicit where the API cannot prove the cause.

Routine synchronization must not call the guest. Signup readiness and user-requested actions may contact Pilot with bounded retries.

## Cargo readiness after Friday

Cargo already creates a Framework webhook for Object Storage Cluster. Reuse that source rather than inventing a generic Cargo event stream.

The configured event is `on_update` with Active or Failed status. It describes cluster provisioning, not continuous cluster health.

The inspected payload still sets `service_endpoint` to `<TBD>`. It also omits the cluster ID and observation timestamp. Its generated condition does not restrict the webhook to its named cluster.

Correct those sender details in a small Cargo PR before enabling Central registration. Restrict each generated webhook to its own cluster.

Atlas's Cargo provisioning currently supplies placeholder Central URL and secret values. Configure the real staging URL and shared secret through the supported settings.

Replay or regenerate the webhook after configuration. Prove delivery from an existing cluster as well as a new status transition.

Central's receiver must not register an Active backend with a placeholder or invalid endpoint. Store only verified service addresses.

Cargo health uses separate fields. Do not label the cluster healthy from a provisioning event. Live health reporting and new service ordering are later work.

No new Cargo cluster bootstrap from Central is required for the default staging milestone. Atlas and Cargo own the existing regional infrastructure.

## Rename, routes, and TLS after Friday

Reuse the existing Pilot Admin API.

| Operation | Pilot endpoint |
|---|---|
| Rename site | `POST /api/v1/sites/<name>/actions/rename` with `new_name` and `keep_old_hostname`. |
| Rename admin domain | `POST /api/v1/settings/admin-domain` with `domain` and optional `tls`. |
| DNS guidance | `GET /api/v1/sites/<name>/domains/<domain>/dns-records`. |
| Attach domain | `POST /api/v1/sites/<name>/domains`. |
| Remove domain | `DELETE /api/v1/sites/<name>/domains/<domain>`. |
| Enable site TLS | `POST /api/v1/sites/<name>/actions/enable-tls`. |

Store returned task IDs and follow the task result. An accepted response is not completion. Use the rename endpoints' idempotency key support.

Central keeps the stable Site identity while the Pilot site name changes. Update the Pilot address only after admin rename succeeds. Preserve an automatic management alias for recovery.

Do not assume domain attachment enables TLS. Pilot's domain application issues certificates when SSL is already enabled. Use the TLS operation when required.

| Name | Route owner | TLS owner |
|---|---|---|
| Automatic VM name | Proxy computes the VM address. No map write. | Proxy regional wildcard certificate. |
| Friendly regional name | Proxy site map. | Proxy regional wildcard certificate. |
| Customer domain | Proxy domain map to the VM. | Pilot on the VM. |

Atlas provisions the regional proxy and its wildcard certificate. Its tenant VM API has no customer-domain route. The separate proxy control API applies map changes.

Pilot's `bench-domain-provider` is optional. The inspected image setup does not establish a complete Central route provider contract.

Use one Central orchestration path: authorize and reserve the name, verify DNS ownership, apply its proxy route, then call Pilot. Record progress and compensate on failure.

Use this direct path only after checking the selected image's provider. If that provider owns routing, agree on its Central call contract and use it instead.

Never let both paths mutate the route independently. Do not give a customer VM an unrestricted regional proxy token.

Wildcard or shared-proxy DNS resolution alone does not prove customer ownership. Require a domain-specific ownership check before a route can move between Teams.

The proxy forwards customer HTTPS as TLS with PROXY protocol v2 to VM port 443. Verify Pilot's proxy mode and HTTP challenge reachability on the actual image.

Certificates and renewal stay in Pilot. Central stores the domain claim, operation result, and useful failure information. Do not implement a certificate authority client or a new Pilot certificate endpoint.

Use per-name map mutations. Keep domain uniqueness and pending claims durable. A small domain record is justified if existing records cannot enforce this safely.

## Patches and staging cutover

Staging-only deployment permits a maintenance window and coordinated service updates. It does not permit silent data loss.

Add patches for required fields, data backfills, and references. Keep indexes and constraints in controller hooks, with valid migration ordering.

Inventory partially applied earlier rewrite data. Preserve verified tenant mappings, Central resource identities, and subscription links.

Back up the database and private files before cutover. Pause affected mutations and workers. Validate records and regional calls before resuming them.

Do not migrate unrelated schemas, rename Asset, merge Atlas Instance, or redesign subscriptions for Friday.

Remove obsolete regional mutation paths when their replacements land. Do not leave a dashboard control that calls a removed endpoint or reports false success.

## After Friday

The wider rewrite remains planned, but it is not part of the staging deadline.

| Area | Later work |
|---|---|
| API surface | Reusable typed core, OpenAPI, generated Central clients, and migration of remaining routes. |
| Data model | Asset-to-Server rename, Region consolidation, and focused data patches. |
| Images | Synchronized catalog, prepared-shape fields, release metadata, and product choices. |
| Lifecycle | Resize/migration, snapshot, console streaming, richer operation progress, and fleet-scale scheduling. |
| Rename and domains | Site/admin rename, customer domains, certificates through Pilot, broader DNS cases, and multi-site products. |
| Services | Cargo readiness registration, new service ordering, live health, storage/LLM policy, and telemetry. |
| Standards | IAM, partners, notifications, services, module specifications, and shared dashboard cleanup. |
| Release | Full populated migration rehearsal and evidence for the user's merge into develop. |

Keep billing calculations and its public API outside the rewrite. Review every necessary billing integration change with focused and full billing tests.
