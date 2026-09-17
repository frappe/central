# Resource actions

## Purpose

Resource Action owns the durable intent and outcome of server creation, start, stop, and termination. Asset is the observed server mirror. An action is not proof of the server's current state.

```text
Customer -> authorized service -> Resource Action -> queued integration worker
                                      |                      |
                                saved configuration       Atlas tenant API
                                      |                      |
                                accepted quote       regional VM identity
                                      |                      |
                                 Subscription <--- Asset mirror
```

## Request contract

The server APIs accept a Team, region, display name, image offering, regional image ID, and request key. A preset request adds a plan. A composed request adds a profile and resource quantities. Guest hostname and SSH public keys are separate inputs. Ubuntu requires an SSH key.

Central checks the capability, current image selector, image availability, plan eligibility, resource sizes, and billing policy before saving the action. It locks the Team while reserving budget. Pending requests count toward the trial server limit and paid spending limit. Whole positive virtual CPUs are required. Memory and disk must resolve to positive whole MiB values. The disk must fit the image.

The request key is unique within a Team. Reusing it with identical inputs returns the same action. Reusing it with changed inputs fails. The saved configuration contains the accepted shape, image identity, currency, and billing cycle. The reserved rate becomes the opening subscription price even if the catalog changes while the request waits.

API routes remain thin. `central/server_models.py` defines input and saved-configuration models. `central/server_provisioning.py` owns creation policy. `central/resource_actions.py` owns power-operation authorization. Remote calls and mirror writes belong to `central/integrations/`.

## State and recovery

| State | Meaning and next action |
|---|---|
| Queued | Intent is saved. The worker rechecks the requester's capability before dispatch. |
| Dispatching | The dispatch marker is committed before the remote mutation. A replacement worker must not send it again. |
| Sent | Atlas accepted the request and Central saved its VM identity. Local finalization or observation can be retried. |
| In Progress | A scoped read has not confirmed the target state. |
| Uncertain | The mutation may have succeeded. A known VM can be checked by read. An unknown creation needs operator resolution. |
| Succeeded | A scoped read confirmed the target state, or termination returned a scoped not-found response. |
| Failed | A definite rejection or observed failure is recorded. The record retains the error and any accepted VM identity. |
| Timed Out | A historical terminal state. Elapsed time alone does not prove failure or permit a repeated create. |

The worker saves the remote VM identity before billing or mirror finalization. A local failure retains that identity and a readable error. Recovery retries local finalization and regional reads. It does not repeat the create call.

The scheduled recovery job selects old queued or accepted actions. Unresolved creations without a VM identity do not consume its batch. Redis and database locks serialize workers. Customer retries cannot change an existing action's payload.

An operator can use **Locate Created VM** for an uncertain creation. Central verifies the VM ID, tenant, selected image, and `central_action_id` metadata before binding it. **Check Progress** queues another safe check. Both operations enforce permissions on the server.

## Pilot and Ubuntu

A Pilot creation issues one credential before dispatch. Atlas receives the `pilot-central` metadata document with the Central endpoint, bearer token, public-key endpoint, and audience ID. Central stores the token hash, not its plaintext, and keeps credentials outside the saved request payload and customer status.

An accepted Pilot VM is linked to its credential during local finalization. Its management gateway uses Atlas's `proxy_hostname_suffix`. A running VM does not prove that Pilot or a site is ready. Site readiness and signup belong to the next phase.

Ubuntu receives its SSH keys and guest hostname. It does not receive a Pilot credential or wait for a site.

## Errors and permissions

Customer status uses one response shape: `action`, `status`, `resource_id`, `title`, and an optional structured `error`. Errors include a stable code, message, remediation, and retry indication. Network loss after mutation is an unknown outcome. A failed read never means the VM was deleted.

Creation requires `server:create`. Start and stop require `server:power`. Termination requires `server:terminate`. Customer status reads require `server:view` for the owning Team. Customers cannot insert or edit Resource Action documents directly. Query conditions and document permissions enforce the same Team boundary.

A scoped not-found response terminates the existing mirror, applies the billing cancellation hook, and revokes that server's Pilot credentials. A response for a different VM or tenant is rejected without updating the mirror.

## Console and limits

The console selects region, offering, exact build, and compatible plan. It retains the original request key and payload in session storage until a response is confirmed. Page reloads resume a known action. An unconfirmed HTTP response can resume only the original request. Switching Teams clears the visible action and ignores late responses from the previous Team.

Restart and resize are not exposed by this action flow. Restart needs an authoritative completion signal. Resize needs Atlas migration tracking before billing can change safely. Framework webhook ingestion and signup site readiness are subsequent delivery phases.

## Validation

The focused suites are `test_resource_actions`, `test_resource_action_migration`, `test_atlas_sync`, `test_server_observation`, `test_pilot_credential_delivery`, `test_atlas_errors`, and the billing create and trial tests. See [cutover coverage](../../../../spec/CUTOVER_TEST_COVERAGE.md) for the retained requirements and retired interfaces.
