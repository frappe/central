# Atlas integration test coverage

## Purpose

This document names the test module that owns each requirement of the Atlas, Pilot, and Cargo integration. Change the owning module when you change the behavior. Do not restore a removed interface only to satisfy an old test.

## Which module owns each requirement?

| Requirement | Test owner |
|---|---|
| Region identity, tenant header, signing, disabled regions and connection failures | `central.tests.test_regional_configuration` |
| Image selectors, availability, pagination, customer permissions and cross-Team denial | `central.tests.test_image_offerings` |
| Whole CPUs, valid resource sizes and image disk fit | `central.tests.test_server_provisioning_shapes` |
| Persist before dispatch, duplicate requests, lost responses and recovery by read | `central.tests.test_resource_actions` |
| Credential bootstrap, secret exclusion, permission revocation and uncertain VM matching | `central.tests.test_resource_actions` |
| Power commands, intent before dispatch, confirmation by read and timeouts | `central.tests.test_atlas_sync` |
| Credential revocation and ownership on confirmed absence | `central.tests.test_pilot_credential_delivery` |
| Scoped VM reads, confirmed absence, billing cancellation hook and identity preservation | `central.tests.test_server_observation` |
| Mirror ordering, duplicate insert recovery and row locking | `central.tests.test_server_observation` |
| Explicit rejection, uncertain mutation outcomes and safe customer errors | `central.tests.test_atlas_errors` and `central.tests.test_errors` |
| Signed state delivery receiver, refusals and report ordering | `central.tests.test_state_delivery` |
| Cargo enrollment and registration | `central.tests.test_cargo_enrollment` |
| Server resize | `central.tests.test_server_resize` |
| VM snapshots | `central.tests.test_vm_snapshots` |
| Team SSH keys | `central.tests.test_team_ssh_keys` |
| Site domains and proxy routes | `central.tests.test_site_domain` |
| Trial sites | `central.tests.test_sites` |
| Scoped role grants | `central.tests.test_resource_scoping` |
| Region field migration | `central.tests.test_region_field_migration` |
| Resource Action migration | `central.tests.test_resource_action_migration` |

## Which billing tests cover the integration?

| Billing tests | Coverage |
|---|---|
| Create and trial integration tests | Real subscription, Subscription Change lock, trial credit, spending limit, and resource limit behavior. Only the regional transport is replaced. |
| Capacity tests | Image compatibility and unmeasured placement capacity. |
| Resize tests | Billing-domain ledger and failure checks. They stop at the runtime adapter. `central.tests.test_server_resize` covers the adapter. |

See [Validation](LOCAL_ENVIRONMENT.md) for the staging evidence that tests cannot give.
