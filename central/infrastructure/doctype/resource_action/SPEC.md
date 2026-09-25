# Resource actions

## Purpose

Resource Action owns the durable intent and outcome of server creation, resize, start, stop, restart, and termination. Virtual Machine is the server record. Its observed fields hold the last state a region reported. An action is not proof of the server's current state.

```text
Customer -> authorized service -> Resource Action -> queued integration worker
                                      |                      |
                                saved configuration       Atlas tenant API
                                      |                      |
                                accepted quote       regional VM identity
                                      |                      |
                                 Subscription <--- Virtual Machine record
```

## Request contract

The server APIs accept a Team, region, display name, image offering, regional image ID, and request key. A preset request adds a plan. A composed request adds a profile and resource quantities. Guest hostname and SSH public keys are separate inputs. Ubuntu requires an SSH key. One request can contain at most 20 SSH keys, and each key can contain at most 16,384 characters.

Central checks the capability, current image selector, image availability, plan eligibility, resource sizes, and billing policy before saving the action. It locks the Team while reserving budget. Pending requests count toward the trial server limit and paid spending limit. A server can use from 1 through 32 whole virtual CPUs. Memory and disk must resolve to positive whole MiB values. The disk must fit the image.

The request key is unique within a Team. Reusing it with identical inputs returns the same action. Reusing it with changed inputs fails. The saved configuration contains the accepted shape, image identity, currency, and billing cycle. The reserved rate becomes the opening subscription price even if the catalog changes while the request waits.

A repeat under a new key is also answered with the saved action, when the same requester sent the same settings and no region has returned a VM identity yet. Central saves the request before it calls a region, so a lost reply leaves the record while the caller keeps nothing. A request that already holds a VM identity never matches, so a deliberate second server is still a second record. The request digest covers the settings only, not the key.

API routes remain thin. `central/server_models.py` defines input and saved-configuration models. `central/server_provisioning.py` owns creation policy. `central/resource_actions.py` owns power-operation authorization. Billing catalog modules own purchase and repricing policy. Remote calls and observed-state writes belong to `central/integrations/`. Resource Action queues every server and trial-site operation after the request transaction commits.

## Console API

| Operation | Method and inputs | Capability | Result |
|---|---|---|---|
| List the fleet | `GET central.api.servers.registry(team)` | `server:view` | Servers include `region`. Sites include their machine region. Unfinished creations are returned separately. |
| Read one server | `GET central.api.servers.server_overview(team, resource_id)` | `server:view` | The server contains its `region`; `region_details` contains its display name, provider, and country code. |
| Create a preset server | `POST central.api.servers.create_server(team, region, title, request_key, plan, offering, image_id, ...)` | `server:create` | A queued Action Status. |
| Create a custom server | `POST central.api.servers.create_composed_server(team, region, title, request_key, includes, sub_category, offering, image_id, ...)` | `server:create` | A queued Action Status. |
| Start, stop, or restart | `POST central.api.servers.<action>_server(team, resource_id)` | `server:power` | A queued Action Status. |
| Resize | `POST central.api.servers.resize_server(team, resource_id, plan or includes, ...)` | `server:resize` | A queued Action Status and subscription identity. |
| Terminate | `POST central.api.servers.terminate_server(team, resource_id, take_snapshot)` | `server:terminate`; also `server:snapshot` when requested | A queued Action Status. |
| Read progress | `GET central.api.servers.action_status(name)` | `server:view` on the action's Team | Current Action Status. |
| Retry a failed creation | `POST central.api.servers.retry_action(name)` | `server:create` on the action's Team | The same action returned to Queued. |

Action Status contains `action`, `status`, `resource_id`, `title`, and an optional customer-safe error. Mutations are asynchronous. A successful HTTP response means Central saved the operation, not that the region completed it. The caller reads progress from the action or the fleet. The action's Team is the ownership boundary for both the route and direct document access.

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
| Timed Out | A power, restart, or terminate command did not reach its goal within 10 minutes of dispatch. A creation never times out, and elapsed time never permits a repeated create. |

The worker saves the remote VM identity before billing or local finalization. A local failure retains that identity and a readable error. Recovery retries local finalization and regional reads. It does not repeat the create call. A resize saves its absolute target before dispatch. Recovery observes the current shape before it sends another resize, and billing changes only after the observed shape matches the target.

The scheduled recovery job selects old actions that have not finished. Redis and database locks serialize workers. Customer retries cannot change an existing action's payload. A power, resize, or terminate request cannot start while another action is pending for the same server. `ResourceAction.get_pending` owns this rule: it returns the pending action when the request repeats it, and refuses a different one. `ResourceAction.queue` saves every new action, and `ResourceAction.is_allowed` rechecks the requester before dispatch against the one `ACTION_CAPABILITIES` map. `ResourceAction.fail` records an Atlas or validation error: an uncertain reply becomes Uncertain and any other error becomes Failed. `ResourceAction.finish` settles a create or a command from the observed server status and `GOAL_STATUS`.

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

A Pilot creation issues one credential before dispatch. Atlas receives the `pilot-central` metadata document with the Central endpoint, bearer token, public-key endpoint, audience ID, and the signing key set itself. The keys travel with the credential so the Pilot's first token needs no fetch, and a boot before Central is reachable still verifies. Central stores the token hash, not its plaintext, and keeps credentials outside the saved request payload and customer status. A creation that fails before the region accepts a machine revokes this credential. An Uncertain creation keeps it until a completed search settles the request.

An accepted Pilot VM is linked to its credential during local finalization. Its management gateway uses Atlas's `proxy_hostname_suffix`. A running VM does not prove that Pilot or a site is ready. Site readiness and signup belong to the next phase.

Ubuntu receives its SSH keys and guest hostname. It does not receive a Pilot credential or wait for a site.

## Idle sleep

A trial server sleeps after the idle time on Central Settings, which is 30 minutes by default. Customer traffic wakes it. Zero minutes keeps trial servers awake.

A paid server never sleeps. A resize ends sleep for good, because a server its owner has resized has outgrown the hobby comfort. Atlas takes the idle timeout on its own while the server runs, so ending sleep never stops it.

## Errors and permissions

Customer status uses one response shape: `action`, `status`, `resource_id`, `title`, and an optional structured `error`. Errors include a stable code, message, remediation, and retry indication. Network loss after mutation is an unknown outcome. A failed read never means the VM was deleted.

Desk links the action to its latest Error Log. Regional failures and unexpected local failures store their full traceback without local variables in Error Log, while the action keeps only its customer-safe error envelope. Linked Error Log records retain the incident history. Customer responses state what happened, the effect on the request, and the next safe action. They never include service names, configuration values, or operator diagnostics.

The request digest, Pilot credential, and Error Log link use permission level 1 for System Manager. This boundary is required because a Central User can read an authorized Resource Action through the standard document API even when that user has no Desk access.

Creation requires `server:create`. Start, stop, and restart require `server:power`. Resize requires `server:resize`. Termination requires `server:terminate`. A terminate with `take_snapshot` also requires `server:snapshot`, and it destroys the server only after its final snapshot is Available. See [VM snapshots](../vm_snapshot/SPEC.md#terminate-with-a-snapshot). Customer status reads require `server:view` for the owning Team. Customers cannot insert or edit Resource Action documents directly. Query conditions and document permissions enforce the same Team boundary.

A scoped not-found response records the server as terminated, applies the billing cancellation hook, and revokes that server's Pilot credentials. A response for a different VM or tenant is rejected without recording anything.

## Console and limits

The console selects region, offering, exact build, and compatible plan. It keeps no copy of the request: `central.api.servers.registry` returns the team's unfinished creations, and the form picks up the one this user started. A page reload, a second tab and a lost reply all reach the same record instead of starting another. Switching Teams clears the visible action and ignores late responses from the previous Team.

Resize uses the same action flow. `central.api.servers.resize_server` validates the target and inserts the action. The integration grows a disk online when CPU and memory stay the same. When CPU or memory changes, it stops the VM and sends the full CPU, memory, and disk target. A server with idle sleep on also receives a resize call that changes only the idle time, which turns sleep off. The integration starts the VM, records the observed shape, and then asks billing to reprice. A billing failure leaves the action at Sent, so recovery can finish the local change without repeating a confirmed remote resize.

## Validation

The focused suites are `test_resource_actions`, `test_resource_action_migration`, `test_atlas_sync`, `test_server_observation`, `test_server_resize`, `test_pilot_credential_delivery`, `test_atlas_errors`, and the billing create, trial, and resize tests. See [cutover coverage](../../../../spec/CUTOVER_TEST_COVERAGE.md) for the retained requirements and retired interfaces.
