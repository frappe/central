# Resource actions

## Purpose

Resource Action owns the durable intent and outcome of server creation, start, stop, and termination. Asset is the server record, and its observed fields hold the last state a region reported. An action is not proof of the server's current state.

```text
Customer -> authorized service -> Resource Action -> queued integration worker
                                      |                      |
                                saved configuration       Atlas tenant API
                                      |                      |
                                accepted quote       regional VM identity
                                      |                      |
                                 Subscription <--- Asset record
```

## Request contract

The server APIs accept a Team, region, display name, image offering, regional image ID, and request key. A preset request adds a plan. A composed request adds a profile and resource quantities. Guest hostname and SSH public keys are separate inputs. Ubuntu requires an SSH key.

Central checks the capability, current image selector, image availability, plan eligibility, resource sizes, and billing policy before saving the action. It locks the Team while reserving budget. Pending requests count toward the trial server limit and paid spending limit. Whole positive virtual CPUs are required. Memory and disk must resolve to positive whole MiB values. The disk must fit the image.

The request key is unique within a Team. Reusing it with identical inputs returns the same action. Reusing it with changed inputs fails. The saved configuration contains the accepted shape, image identity, currency, and billing cycle. The reserved rate becomes the opening subscription price even if the catalog changes while the request waits.

A repeat under a new key is also answered with the saved action, when the same requester sent the same settings and no region has returned a VM identity yet. Central saves the request before it calls a region, so a lost reply leaves the record while the caller keeps nothing. A request that already holds a VM identity never matches, so a deliberate second server is still a second record. The request digest covers the settings only, not the key.

API routes remain thin. `central/server_models.py` defines input and saved-configuration models. `central/server_provisioning.py` owns creation policy. `central/resource_actions.py` owns power-operation authorization. Remote calls and observed-state writes belong to `central/integrations/`.

## State and recovery

| State | Meaning and next action |
|---|---|
| Queued | Intent is saved. The worker rechecks the requester's capability before dispatch. |
| Dispatching | The dispatch marker is committed before the remote mutation. A replacement worker must not send it again. |
| Sent | Atlas accepted the request and Central saved its VM identity. Local finalization or observation can be retried. |
| In Progress | A scoped read has not confirmed the target state. |
| Uncertain | The mutation may have succeeded and the region could not be reached to find out. A creation is looked up again on the next sweep. |
| Succeeded | A scoped read confirmed the target state, or termination returned a scoped not-found response. |
| Failed | A definite rejection or observed failure is recorded. The record retains the error and any accepted VM identity. |
| Timed Out | A historical terminal state. Elapsed time alone does not prove failure or permit a repeated create. |

The worker saves the remote VM identity before billing or local finalization. A local failure retains that identity and a readable error. Recovery retries local finalization and regional reads. It does not repeat the create call.

The scheduled recovery job selects old actions that have not finished. Redis and database locks serialize workers. Customer retries cannot change an existing action's payload.

A creation the region never answered settles itself. Central stamps its action ID into the guest metadata of every create, so it asks the region what that request built. The region lists newest first, and the search stops at the first machine older than the dispatch. A machine counts only when its tenant, image and action marker all match, so another request's machine is never adopted.

| Search result | Outcome |
|---|---|
| A matching machine | Central records its identity and the creation carries on. |
| No matching machine | The creation failed and nothing was built. The customer can send it again. |
| The region could not be reached | Nothing is decided. The request stays open for the next sweep. |

Only a search that completed can report that nothing was built, so an unreachable region never turns into a false failure. **Check Progress** queues another safe check and enforces permissions on the server.

## Retry

A failed creation is sent again on its own record, through `retry`. The record already holds the validated configuration, the request key and the accepted quote, so nothing about the request changes and no second record opens.

| Condition | Result |
|---|---|
| A creation that failed or timed out, with no VM identity | The record returns to Queued and dispatches again. |
| Any record that already holds a VM identity | Refused. That identity is the region's receipt, and a second dispatch would build a second server. |
| A creation that is still running, including one waiting on a lookup | Refused. **Check Progress** is the safe read for a request in flight. |
| Start, stop, restart, and terminate | Refused. These are repeated from the server, which opens a fresh record. |

A retry requires `server:create` and re-checks the plan, the trial limit and the team's remaining spending headroom, because a failed request holds no reserved budget. The reserved rate itself does not change.

## Pilot and Ubuntu

A Pilot creation issues one credential before dispatch. Atlas receives the `pilot-central` metadata document with the Central endpoint, bearer token, public-key endpoint, and audience ID. Central stores the token hash, not its plaintext, and keeps credentials outside the saved request payload and customer status.

An accepted Pilot VM is linked to its credential during local finalization. Its management gateway uses Atlas's `proxy_hostname_suffix`. A running VM does not prove that Pilot or a site is ready. Site readiness and signup belong to the next phase.

Ubuntu receives its SSH keys and guest hostname. It does not receive a Pilot credential or wait for a site.

## Errors and permissions

Customer status uses one response shape: `action`, `status`, `resource_id`, `title`, and an optional structured `error`. Errors include a stable code, message, remediation, and retry indication. Network loss after mutation is an unknown outcome. A failed read never means the VM was deleted.

Creation requires `server:create`. Start and stop require `server:power`. Termination requires `server:terminate`. Customer status reads require `server:view` for the owning Team. Customers cannot insert or edit Resource Action documents directly. Query conditions and document permissions enforce the same Team boundary.

A scoped not-found response records the server as terminated, applies the billing cancellation hook, and revokes that server's Pilot credentials. A response for a different VM or tenant is rejected without recording anything.

## Console and limits

The console selects region, offering, exact build, and compatible plan. It keeps no copy of the request: `central.api.servers.registry` returns the team's unfinished creations, and the form picks up the one this user started. A page reload, a second tab and a lost reply all reach the same record instead of starting another. Switching Teams clears the visible action and ignores late responses from the previous Team.

Resize is not exposed by this action flow. It runs as a billing background job instead: `central.integrations.servers.resize_server` stops the VM when CPU or memory changes, sets compute with `PATCH /virtual-machines/<id>/compute`, grows the disk with `PATCH /virtual-machines/<id>/disk`, starts the VM, and waits up to 240 seconds for each power state. Billing re-prices only after these calls succeed. Framework webhook ingestion and signup site readiness are subsequent delivery phases.

## Validation

The focused suites are `test_resource_actions`, `test_resource_action_migration`, `test_atlas_sync`, `test_server_observation`, `test_pilot_credential_delivery`, `test_atlas_errors`, and the billing create and trial tests. See [cutover coverage](../../../../spec/CUTOVER_TEST_COVERAGE.md) for the retained requirements and retired interfaces.
