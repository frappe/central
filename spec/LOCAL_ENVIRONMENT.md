# Staging integration validation

## Purpose

Prove the [Friday scope](REWRITE_SCOPE.md) against the selected source and deployed revisions. Source inspection does not replace a real staging run.

## Source check

The local source check fetched Atlas, Pilot, and Cargo develop. Pilot admin upgrade completed with no new develop commit and preserved local source edits.

Reviewed revisions: Atlas `7eadeda7`, Pilot `228c46fa`, Cargo `2b7845d`, and Framework `3f96501d86`.

Record the actual staging versions separately. Verify that its image contains the expected aliases, proxy configuration, and Pilot APIs.

## Environments

| Environment | Required proof |
|---|---|
| Contract tests | Create payloads, callback signatures, duplicates, ordering, task tracking, and failure recovery. |
| Disposable populated database | Required patches preserve Team mappings, resource identities, credentials, and billing references. |
| Real staging region | Signup, site login, Pilot access, Ubuntu SSH access, power actions, callbacks, sleep, wake, and cleanup. |

A separate source worktree is not automatically installed into a bench. Configure the validation bench to use the correct branch before running tests.

Use Pilot for Frappe commands. Use the commands in CLAUDE.md for lint, tests, and build. Do not migrate a shared database merely to validate a proposed patch.

## Identity and bootstrap tests

Use Central tokens with the real Atlas and Pilot verifiers. Check wrong audiences, missing tenant headers, and cross-Team access.

Test concurrent tenant allocation, preserved mappings, key publication, and denied non-operator key changes.

Test metadata validation, initial key-cache setup, interrupted bootstrap, and credential binding to the correct VM.

## Framework webhook tests

Use Framework's actual serializer and signature producer in the contract tests. Verify against the exact received bytes, including Unicode and whitespace cases.

| Case | Expected result |
|---|---|
| First state document save | The configured webhook delivers the initial observation. |
| Later status change | The receiver stores and applies the new observation. |
| Unchanged host report | The tested condition suppresses needless delivery. |
| Invalid signature or unknown sender | Uniform rejection and no state write. |
| Repeated payload | One receipt identity and no repeated lifecycle effects. |
| Older observation | No state regression. |
| Event before create response | Pending receipt is matched after the resource link exists. |
| Receiver crash after persistence | The recovery sweep resumes processing. |
| Sender failure after database commit | Repair reads recover the observation. |
| Delivery exhaustion | The failure is visible in Webhook Request Log and Central remains repairable. |
| VM deletion | A scoped API read confirms absence despite the missing state-row deletion event. |
| Sleeping VM reports stopped | No false shutdown, failure, or subscription cancellation. |

Verify first-save and change conditions on the deployed Framework, not only on a mocked document.

Configure retries explicitly. Verify the sender's scheduler and worker queue. A stored Webhook record alone does not prove delivery.

Do not require a new Atlas event queue. Central's durable receipts cover accepted messages, while repair reads cover events that never arrive.

## Server lifecycle tests

Use the approved Pilot and plain Ubuntu images. Check the readiness rule for each image type.

| Case | Expected result |
|---|---|
| Pilot server creation | Correct Team and VM credential, automatic admin URL, and successful Pilot login. |
| Ubuntu creation | Correct size and SSH key setup. No Pilot credential or Site record is required. |
| Access controls | Pilot controls appear only on a Pilot-managed server. Ubuntu shows supported SSH access information. |
| Explicit stop | Requested and observed state converge to stopped. Customer traffic does not wake it. |
| Start | Requested and observed state converge to running. |
| Restart | An authoritative completion signal confirms the action. A repeated running event is insufficient. |
| Delete | Confirmation, scoped absence check, credential revocation where applicable, and one billing effect. |
| Unknown response | The operation remains recoverable without blind creation or action retries. |
| Another Team | List, document, mutation, and Pilot login access are denied. |

Record the actual Ubuntu access path. A private mesh address alone does not establish customer SSH access.

## Friday end-to-end sequence

1. Sign up as a customer and create the customer's Team.
2. Request one trial and confirm one VM and one prepared site.
3. Observe a signed state update and complete site login.
4. Create a separate Pilot server and open its admin from Central.
5. Create a plain Ubuntu server and verify its size and SSH access.
6. Stop, start, and restart each server type. Confirm the actual results.
7. Let the trial VM sleep while Central synchronization remains active.
8. Send customer traffic and confirm wake and site access.
9. Interrupt callback delivery and prove recovery through repair reads.
10. Use a second Team to verify denied access and operations.
11. Delete the test resources and confirm remote absence and credential cleanup.

Use agreed automatic DNS names, a resource budget, and disposable customer data. Record resource IDs for cleanup.

Test both warm and cold startup. Record latency as evidence, not as a guaranteed performance promise.

## After Friday: Cargo webhook tests

Use the Object Storage Cluster source and its existing receiver path. Verify Active and Failed states separately.

Require an actual gateway endpoint, cluster identifier, and observation time. Reject placeholder addresses.

Test two cluster records to prove a generated webhook cannot send another cluster's state under the wrong identity.

Verify a configured existing cluster can report after setup. Do not wait for a new provisioning cycle to test delivery.

Keep health assertions separate from status assertions. Cargo's health updates are not part of the default provisioning webhook.

## After Friday: rename and domain tests

Use the existing site rename, admin-domain rename, domain, and TLS endpoints. Track returned task IDs through success and failure.

Verify the selected image's domain provider before choosing the route writer. Prove route coordination before declaring the domain flow complete.

| Case | Evidence |
|---|---|
| Site rename | New name works, Central Site identity stays stable, and old-name behavior matches the request. |
| Admin rename | Task succeeds and the management alias still reaches Pilot. |
| Domain attachment | Ownership is verified and the correct regional proxy map points to the VM. |
| TLS enablement | Pilot holds a valid certificate and the public HTTPS request succeeds. |
| TLS transport | Pilot accepts PROXY protocol v2 and the HTTP challenge reaches the guest. |
| Domain failure | Pending claim and error remain visible. Retry or cleanup is safe. |
| Domain removal | Pilot configuration and the owned proxy route are removed without affecting another domain. |
| Cross-Team claim | A second Team cannot take an existing or pending domain claim. |

A successful domain attachment response does not prove certificate readiness. A task acceptance response does not prove completion.

## Migration and handover

Test the actual staging source schema, including any partially applied earlier rewrite. Run required patches twice and verify identities and references.

Record backups, maintenance steps, validation results, and how to restore local data. A database restore does not reverse a remote VM operation.

Each PR records checks and unresolved dependencies. The Friday report records the real journey results and any remaining blocker.

Do not put credentials, private keys, or raw credential metadata in fixtures, screenshots, delivery payloads, or PR descriptions.
