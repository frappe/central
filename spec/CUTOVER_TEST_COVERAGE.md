# Atlas cutover test coverage

## Purpose

Keep the existing tests until their requirements have an explicit replacement or are retired with the corresponding interface. Do not restore removed interfaces only to satisfy their old tests.

## Current checks

| Requirement | Current test owner |
|---|---|
| Region identity, tenant header, signing, disabled regions and connection failures | `central.tests.test_regional_configuration` |
| Image selectors, availability, pagination, customer permissions and cross-Team denial | `central.tests.test_image_offerings` |
| Whole CPUs, valid resource sizes and image disk fit | `central.tests.test_server_provisioning_shapes` |
| Persist before dispatch, duplicate requests, lost responses and recovery by read | `central.tests.test_resource_actions` |
| Credential bootstrap, secret exclusion, permission revocation and uncertain VM matching | `central.tests.test_resource_actions` |
| Scoped VM reads, confirmed absence, billing cancellation hook and identity preservation | `central.tests.test_server_observation` |
| Mirror ordering, duplicate insert recovery and row locking | `central.tests.test_server_observation` |
| Explicit rejection, uncertain mutation outcomes and safe customer errors | `central.tests.test_atlas_errors` and `central.tests.test_errors` |

## Existing tests to adapt or retire

| Existing module | Treatment |
|---|---|
| `test_atlas_sync` | Keep mirror, permissions, billing and recovery requirements. Adapt them to tenant reads and persisted actions. Retire tests for removed event envelopes and Atlas-owned sites. |
| `test_atlas_register` | Retire tunnel handshake assertions. Signed regional configuration tests cover the replacement connection. |
| `test_atlas_webhook_signature` | Retire the old custom webhook contract. Framework webhook receiver coverage belongs to the next phase. |
| `test_atlas_instance` | Replace API-key and tunnel client assertions with signed tenant client and region configuration tests. |
| `test_frappe_version` | Replace version aliases and fallback assertions with regional image discovery and exact build selection tests. |
| `test_pilot_credential_delivery` | Replace enrollment and echoed-event assumptions with the `pilot-central` metadata and durable action tests. Preserve revocation and ownership tests. |
| Billing create and trial integration tests | Adapt the transport fixture and action result. Preserve subscription, spending limit, trial credit and resource limit assertions. |
| Billing capacity tests | Retire removed capacity endpoint assertions. Test image compatibility and unmeasured placement capacity. |
| Billing resize tests | Keep billing-domain tests separate from the runtime adapter. The asynchronous Atlas resize adapter is a later phase. |

## Approval and execution

The user approved this migration of tests. The replacement suites preserve permissions, billing, mirror ordering, credential ownership, and recovery requirements. Tunnel registration, API-key authentication, version fallback, the custom event envelope, and Atlas-owned site operations are retired with their interfaces.

Billing create and trial tests keep real subscription, price-lock, credit, and spending-limit behavior. Only regional transport is replaced. Billing resize tests stop at the runtime adapter and preserve ledger and failure checks. Image compatibility tests replace the removed capacity-preview contract.

See [local validation](LOCAL_ENVIRONMENT.md) for the recorded execution results and remaining staging dependencies.
