# Central v0.2 rewrite

## Purpose

This is the proposed implementation contract for the v0.2 rewrite. It does not describe completed work. Each phase needs review before it merges into `v0.2`.

Central controls identity, access, product choices, and customer operations. Atlas controls regional machines. Pilot controls benches and sites. The regional proxy controls public routes.

Read [Delivery](DELIVERY.md) for branches and phase acceptance. Read [Validation](LOCAL_ENVIRONMENT.md) for the test environments. Follow [CLAUDE.md](../CLAUDE.md) and [the review rules](../.greptile/rules.md) for every change.

## Agreed decisions

| Decision | Requirement |
|---|---|
| Trial owner | Each signup customer has a Central Team. |
| Trial unit | Each trial site has one VM. Do not pool unrelated trial customers on one VM. |
| Network identity | Each Team has one immutable, unique, nonzero unsigned 32-bit tenant ID. A Team name is not a network identity. |
| Sleep | Metal manages VM sleep and wake. Central supplies the idle timeout. |
| Paid upgrade | Keep the Team, tenant ID, and Site identity. Use Atlas for any machine resize or host migration. |
| Deployment | Central is staging-only. A coordinated cutover and maintenance window are acceptable. |
| Compatibility | Do not add old API aliases, mixed-version support, or rolling-upgrade machinery. |
| Existing data | Preserve required staging data with explicit patches. Do not assume a fresh database. |
| Billing | Change only the fields and integration calls required by this rewrite. Keep billing calculations and its public API outside this scope. |
| Branches | Each phase targets `v0.2`. The user merges `v0.2` into `develop` after final acceptance. |

A Team can later own several VMs. Those VMs share its network boundary. Separate VMs under the same tenant ID do not provide cross-Team network isolation.

## Verified baseline

The review used Central `c2565d80`, Atlas `7eadeda7`, and Pilot `228c46fa`. Recheck the contracts against the selected dependency revisions before implementation.

| Source | What it establishes |
|---|---|
| [Atlas tenant API](../../atlas/atlas/docs/tenant-api.md) | Bearer tokens, tenant headers, pagination, status codes, and asynchronous operations. |
| [Atlas security](../../atlas/atlas/docs/security.md) | Tenant isolation, key namespaces, and restricted operator resources. |
| [Atlas architecture](../../atlas/docs/architecture.md) | Placement, host ownership, uncertain create results, and local warm artifacts. |
| [Atlas models](../../atlas/atlas/api/models.py) | Exact public request and response fields. |
| [Proxy control API](../../atlas/services/http-proxy/docs/control-daemon.md) | Named routes, custom domains, reserved names, and retry rules. |
| [Pilot specification](https://github.com/frappe/pilot/blob/228c46fa/SPEC.md) | Server, Bench, Site, and host-wide trust boundaries. |
| [Pilot metadata](https://github.com/frappe/pilot/blob/228c46fa/pilot/integrations/central/metadata.py) | Bootstrap fields and injectable metadata client. |
| [Pilot Admin API](https://github.com/frappe/pilot/blob/228c46fa/docs/admin-api.md) | Site operations, tasks, login, and rename behavior. |

Sibling links assume the standard bench layout. In a detached worktree, use the pinned repository revision or a separate Atlas checkout.

The current Atlas compute route requires a stopped VM for CPU or memory changes. Migration code exists separately. Automatic resize-driven migration is not an accepted Central contract yet.

## Ownership

```text
Customer -> Central Team -> tenant ID
                              |
                              +-> Server -> Atlas VM -> Metal host
                                   |
                                   +-> Site -> Pilot bench and site
                                        |
                                        +-> Site Domain -> proxy route and Pilot certificate
```

| Owner | State and responsibility |
|---|---|
| Central IAM | Users, Team membership, roles, capabilities, and authorization decisions. |
| Central Region | Configured endpoints, numeric region identity, wildcard domain, and observation freshness. |
| Central Server | Stable customer resource identity, Team, product selection, credential link, and remote VM reference. |
| Atlas and Metal | Machine placement, requested runtime configuration, observed runtime state, sleep, and host migration. |
| Central Site | Stable customer site identity, Team, Server link, bench reference, names, and product association. |
| Pilot | Bench and site existence, installed apps, site tasks, and certificates. |
| Central Site Domain | Domain ownership, requested route, and the recorded progress of routing and certificate operations. |
| Proxy | Applied public routes. |
| Central Resource Action | Requested operation, remote references, deadline, progress, error, and recovery state. |

Keep `Server` and `Site` separate. The first trial product has one Site per Server. A separate server product can support several sites owned by the same Team.

Use a stable Central identifier for each Server. Enforce uniqueness of the remote reference within its Region. Never use an Atlas VM name alone as a global identifier.

Keep the bench name as a Site field until Central needs a separate bench lifecycle. Do not add a Bench DocType only to copy Pilot's model.

Preserve commercial fields during remote synchronization. A runtime observation must not overwrite a Team, product selection, title, or subscription reference.

All remote calls belong under `central/integrations/`. Controllers and routes delegate through that layer. Keep one owner for each observation write and its lifecycle effects.

## Phase 0 foundation

### Team identity

Allocate tenant IDs from a persistent sequence. Reserve tenant `0` for infrastructure. Do not reuse a committed tenant ID after Team deletion.

Inventory existing Team IDs and regional resources before allocation. Preserve valid mappings. Stop the migration with a readable conflict report when ownership is ambiguous.

Do not assign fresh IDs to live resources without a matching regional ownership decision. Do not infer the mapping from a display name.

Backfill before enforcing the new invariant on existing rows. Add indexes and unique constraints through `on_doctype_update`, after the data is valid. Test the actual migration order.

### Region

Use one Region record for one regional Atlas deployment and its proxy endpoint. Validate the configured numeric ID against the selected region configuration.

Migrate required Atlas Instance data and Link references before deleting that DocType. Equal names do not prove that every destination Region exists.

The target Region uses public HTTPS and Central-signed tokens. It does not need SSH credentials or a Central-to-Atlas tunnel. Atlas's internal mesh remains Atlas's responsibility.

Do not copy tunnel credentials into the target Region model. Retire Atlas Instance in phase 3 after its remaining callers and data references are handled.

### Signing and credentials

Use Ed25519 keys with a `central:` key identifier for Atlas. Atlas tokens carry `iss=central`, `aud=atlas-admin:<region ID>`, `scope=*`, and `tenant=*`.

The Atlas client supplies `X-Tenant-ID` from the authorized Team. Never accept a customer-supplied tenant header as authority.

Proxy tokens use `aud=atlas-proxy:<region ID>` and no tenant claim. Use the minimum route scope needed by the operation.

Inventory Pilot, Cargo, Datum, and other token consumers before replacing the shared signer. Verify each algorithm, audience, issuer, and scope contract first.

A coordinated key cutover can invalidate staging sessions. Record that effect and how operators refresh them. Do not remove old keys or credentials without a migration decision.

Define key publication, activation, overlap, retirement, and emergency replacement. Prevent concurrent first-use key creation. Key administration requires operator authorization and an audit record.

Do not rotate an active key from a public key-set read. Do not expose private keys, bootstrap credentials, or raw credential metadata in customer responses.

## Signup operation

1. Authenticate the customer and resolve the authorized Team.
2. Validate the trial policy, allowed image, size, region, and existing billing eligibility.
3. Store a durable signup request with a unique client request key.
4. Issue a VM-specific Pilot credential and audience.
5. Create the Atlas VM with the selected shape, sleep policy, and bootstrap metadata.
6. Store the returned regional VM reference and computed automatic names.
7. Confirm bounded Pilot bootstrap and site readiness.
8. Record the existing image site without asking Pilot to create a second site.
9. Return a short-lived site login result through the customer interface.

The image contains the initial bench, site, and hostname aliases. The customer receives a machine-derived name first. A friendly name or custom domain is a later operation.

The `pilot-central` metadata contains `central_endpoint`, `central_auth_token`, `jwks_url`, `jwks_audience_id`, and `initial_jwks_cache`. Use the exact Pilot contract and validate its payload.

Store the credential before the remote request. Bind it to the Server when the VM is known. Keep its delivery secret encrypted while recovery needs it.

Define recovery for every boundary between the Central transaction and the remote operation. A failed database write after remote acceptance must not lose the resource identity.

Central request deduplication alone does not make an Atlas create request safe to repeat. Agree on remote idempotency or a reliable request lookup before automatic create retries.

Until that contract exists, retain an unknown outcome for a timed-out create request. Reconcile or require operator resolution before another create. Never silently create a replacement VM.

Record cleanup failures and retry safe cleanup. Revoke unused credentials after confirmed failed provisioning. Revoke bound credentials after confirmed VM deletion.

Keep quota and trial-abuse controls in Central. Removing a capacity read does not remove authorization, allowed-size checks, billing eligibility, or trial limits.

Keep signing keys and plaintext credentials out of VM list responses, operation payload logs, and customer-visible errors. Do not bake customer identity or credentials into a shared image.

## Images, sleep, and upgrades

The image catalog needs the region, image ID, availability, architecture, allowed product, Pilot release, Frappe version, and prepared machine shape.

Atlas's reviewed image response lacks the prepared CPU, memory, and disk fields. The earlier plan identifies this dependency correctly. Add and test the contract before Central relies on it.

Select an authoritative source for Pilot and Frappe release metadata. Do not parse a human image title to choose a runtime version.

A matching shape permits a warm start. Host cache availability also matters. Test a cold start and show progress instead of promising a fixed startup time.

Metal saves memory and stops an idle VM. Traffic restores its saved state. Sleep preserves the disk and machine identity.

Routine fleet synchronization must not send HTTP requests to a customer VM. Such requests can wake it. Signup readiness and user-requested actions can contact Pilot with bounded retries.

Verify whether metrics, certificate renewal, scheduled jobs, and other traffic affect the idle policy. Decide whether each product permits scheduled work to pause during sleep.

Do not equate `desired_state=running` and `current_state=stopped` with proven health. Check available error and operation information. Add an explicit upstream sleep signal if the UI needs certainty.

An upgrade changes product policy and possibly size or idle timeout. It does not transfer the Site to another Team or create a new subscription identity by default.

Atlas owns physical host selection, capacity checks, migration, and rollback. Central displays supported progress and handles conflicting actions. Do not read Atlas's private host tables.

A host migration can cold-start the guest at cutover. Do not promise that memory sessions survive it. Validate the supported resize sequence against the chosen Atlas release.

## Reconciliation and operation recovery

Central periodically reads Atlas to correct its local view. An operation-specific job reads more often while a customer action is active.

| Rule | Required behavior |
|---|---|
| Scan scope | Scan each relevant Region and tenant pair. Follow every page. There is no whole-region tenant list in the reviewed API. |
| Cost | Budget requests by tenants, pages, and active operations. Do not describe fleet cost as one request per Region. |
| Inventory | Track known Region and Team assignments. Define operator import for unknown tenants. Do not claim discovery of every regional resource. |
| Missing records | Do not infer deletion from an incomplete scan. Confirm absence through a correctly scoped detail read. |
| Error handling | A timeout or server error means stale or unknown state. It does not mean deletion. |
| Hidden records | Atlas also returns `404` for another tenant's resource. Check the stored Region and tenant identity before resolving absence. |
| Concurrent reads | Serialize or reject stale writes for each Server across fleet jobs, focused jobs, and manual refresh. Queue deduplication alone is insufficient. |
| Freshness | Store source observation time when available and local fetch time separately. A delayed list result must not overwrite a newer detail result. |
| Scheduling | Use bounded batches, deadlines, backoff, jitter, and concurrency limits. One slow Region must not block the fleet. |
| Durability | Persist requests before enqueueing. Enqueue after commit. A recovery sweep must find work lost between commit and enqueue. |
| Worker failure | Use expiring work claims or equivalent recovery. Resume unfinished operations after a worker restart. |
| Completion | Check the requested effect. A running VM alone does not prove that a restart or resize completed. |
| Timeout | End the customer's wait with a readable result. Continue safe background observation when the remote outcome remains unknown. |
| Lifecycle effects | Apply credential binding, revocation, action completion, notifications, and required billing effects once. Repeated observations must be safe. |

Keep the requested operation separate from runtime observations. Show a pending operation without pretending that Atlas has already reached its target state.

Define operation completion against the actual API. If restart completion needs a generation or operation ID, add that contract before claiming reliable completion.

Offset pagination can move during concurrent creates and deletes. Use repeated convergence and detail confirmation. A scan is not a consistent database snapshot.

Expose observation age, operation deadline, last error, retry count, and next recovery action. Alert on stale regions, unresolved creates, and repeated cleanup failures.

## Routing and domains

Automatic names encode the VM number and tenant ID below a regional wildcard. They need no proxy map write. Use cross-language test vectors for the encoder and decoder.

Reserve distinct handling for three name types.

| Name type | Route and certificate owner |
|---|---|
| Machine-derived name | Proxy automatic routing and the prepared Pilot hostname alias. Regional wildcard TLS. |
| Friendly regional name | Proxy site map and the Pilot site name or alias. Regional wildcard TLS. |
| Customer domain | Proxy domain map, Pilot site configuration, and a certificate on the VM. |

The proxy domain map rejects names inside the regional wildcard zone. Do not send a friendly regional name to that map.

Central verifies domain ownership before claiming a customer domain. Define normalization, reserved names, uniqueness, and cross-Team denial tests.

Track ownership verification, route application, certificate readiness, and activation separately. Persist retries and cleanup. Never report active while either serving or certificate setup is incomplete.

Use per-name proxy mutations. Do not replace a complete shared regional map for one customer's change.

Agree on Pilot's certificate and routing-provider contract before implementation. Avoid circular calls where Pilot waits on Central while Central waits on the same Pilot task.

Keep a Site's Central ID during rename. On host or region changes, update all affected names and routes. A VM-derived name cannot remain stable across arbitrary VM replacement.

## API and dashboard

Build a small typed API core in Central. Use Atlas's router and OpenAPI pattern as a reference. Keep permissions, tenant resolution, and domain behavior outside the reusable core.

Use `/api/central/v1` for rewritten domains. Define authentication and CSRF behavior for the dashboard before the first mutation route. Do not choose a new external API credential system implicitly.

Start with the existing customer session model. Design separate service or public-client credentials when a concrete caller requires them.

Generate OpenAPI and the dashboard TypeScript client from the same models. Add a drift check. Generate a Python client when a confirmed external caller needs it.

Extract a shared package only after another consumer validates its interface. Do not create a second framework inside Central.

Each route parses, authorizes, and delegates. Enforce both list and document permissions. Keep `central/iam.py` as the Team authorization authority.

Deliver dashboard changes with each behavior. Include loading, empty, stale, failed, disabled, retry, and unknown-outcome states. Keep pages thin and data access in composables.

Apply the Desk requirements from `CLAUDE.md` to each changed operational DocType. An operator must inspect and recover a failed operation without a shell.

## Non-billing scope

| Area | Required review and completion |
|---|---|
| Identity and access | Team boundaries, invitation flows, operator bypass, OAuth consumers, and capability fixtures. |
| Regions and servers | Typed integration, inventory, lifecycle, image selection, operation recovery, and Desk. |
| Sites and domains | Pilot tasks, stable Site identity, login, names, certificates, and cleanup. |
| Services | Catalog, storage, LLM policy, credentials, Cargo configuration, and Team access. |
| Telemetry | Datum token acceptance, labels, credential revocation, and sleep-aware reads. |
| Notifications | Event authority, Team visibility, preferences, failure delivery, and duplicate suppression. |
| Partners | Passport and Connect boundaries, partner membership, credentials, and ownership checks. |
| Dashboard | Domain composables, shared components, typed clients, accessibility, and all request states. |
| Documentation | One authoritative module specification, matching setup guidance, and removal of contradictory contracts. |

Audit each area explicitly. Refactor where the audit finds a concrete violation. A phase may record that an area already meets the rules with supporting evidence.

Rename `Asset` to `Server` when the server model changes. Preserve Central resource names and subscription references where possible. Use a patch for DocType and Link changes.

Do not replace `Subscription.asset_id` and `service_subject` with a new billing model in this rewrite. A necessary Link target update is different from a billing redesign.

## Data migration and staging cutover

Each schema phase includes its migration in the same PR. Test against a populated database and a fresh install.

1. Inventory affected records, secrets, links, pending jobs, and remote resources.
2. Record the exact source schema and any partially applied rewrite state.
3. Take a database and private-file backup before a staging cutover.
4. Pause affected mutations and workers during the cutover.
5. Run patches in the required pre-sync and post-sync order.
6. Validate identity mappings, links, credentials, and record counts.
7. Run integration checks before enabling mutations and workers.

Patches must be safe to repeat after interruption. Fail on ambiguous data instead of selecting an arbitrary owner or deleting records.

Remove a DocType only after its required data and references are handled. Retain useful operation history or define its approved retirement.

Database rollback does not reverse remote machine changes. The cutover runbook must distinguish backup restore from forward recovery of remote operations.

Intermediate `v0.2` phases need not serve old regional APIs. Mark unsupported paths clearly and disable their mutations. A phase must not leave import failures or misleading success states.

Do not deploy `v0.2` as the staging replacement until its declared acceptance gate passes. The final merge to `develop` remains a user decision.

## Decisions that block specific work

| Question | Default or required resolution | Gate |
|---|---|---|
| Existing remote ownership | Preserve verified mappings. Obtain operator input for conflicts. | Phase 0 data patch |
| Token consumers | Prove EdDSA and claim compatibility or coordinate the consumer update. | Phase 0 key cutover |
| Image metadata | Add snapshot shape and identify a release manifest source. | Phase 1 image selection |
| Uncertain create | Agree on remote idempotency or request lookup. Otherwise require explicit resolution before retry. | Phase 2 signup |
| Trial policy | Confirm image, shape, idle timeout, limits, expiry, and scheduled-job behavior. No destructive expiry default. | Phase 2 signup |
| Resize and migration | Confirm public operation progress, completion, and supported states. | Phase 3 resize |
| Custom domains | Confirm certificate issuance, renewal, routing-provider calls, and cleanup. | Phase 4 domains |
| Cargo bootstrap | Agree how each regional Cargo receives its Central endpoint and credentials. | Phase 5 services |

These questions do not block the documentation PR. Each implementation PR must resolve its own gate before it is ready for merge.
