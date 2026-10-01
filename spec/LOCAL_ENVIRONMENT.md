# Staging integration validation

## Purpose

Prove the [baseline scope](REWRITE_SCOPE.md) against the deployed Atlas, Pilot, and Cargo revisions. Source inspection does not replace a real staging run.

Record the actual staging versions. Verify that the image contains the expected aliases, proxy configuration, and Pilot APIs.

## Which environments give which proof?

| Environment | Required proof |
|---|---|
| Contract tests | Create payloads, callback signatures, duplicates, ordering, task tracking, and failure recovery. |
| Disposable populated database | Required patches preserve Team mappings, resource identities, credentials, and billing references. |
| Real staging region | Signup, site login, Pilot access, Ubuntu SSH access, power actions, callbacks, sleep, wake, and cleanup. |

A separate source worktree is not automatically installed into a bench. Configure the validation bench to use the correct branch before you run tests.

Use Pilot for Frappe commands. Use the commands in CLAUDE.md for lint, tests, and build. Do not migrate a shared database only to validate a proposed patch.

## How do I connect a region?

Set the Atlas numeric region ID, the direct base URL, and the proxy domain on the [Region](../central/infrastructure/doctype/region/SPEC.md) form. Initialize the Atlas and Pilot signing keys in Central SSO Settings. A server creation fails before dispatch until the Pilot key exists. Then use the Region form buttons:

1. **Test Connection** makes a signed request and records the result on the record.
2. **Enroll Atlas** sends Central's receiver URL and a webhook secret to Atlas.
3. **Enroll Cargo** registers the region's Cargo connection. The scheduler also retries pending Cargo registration every 10 minutes.

Run `central.tests.test_regional_configuration` and `central.tests.test_image_offerings`. Verify customer read access, operator-only edits, cross-Team denial, pagination, disabled offerings, unavailable images, and malformed regional responses.

Use **Preview Regional Images** on the Pilot and Ubuntu offerings. Confirm the available System builds against the selected region. Pilot selects `purpose=pilot`. Ubuntu selects `purpose=base` and `os=Ubuntu`. Cargo's Pilot image includes a bench and a prepared site for both server and signup flows.

Run the default-offering patch twice and confirm that operator changes stay unchanged. Offerings store no regional image IDs or versions.

Record real staging discovery separately from mocked contract tests. Do not invent image IDs or sizes.

## Identity and bootstrap tests

Use Central tokens with the real Atlas and Pilot verifiers. Check wrong audiences, missing tenant headers, and cross-Team access.

Test concurrent tenant allocation, preserved mappings, key publication, and denied non-operator key changes.

Test metadata validation, initial key-cache setup, interrupted bootstrap, and credential binding to the correct VM.

## State delivery tests

Use Framework's actual serializer and signature producer in the contract tests. Verify against the exact received bytes, including Unicode and whitespace cases. The receiver is `central.api.state_delivery.receive`. See [Inbound webhooks](WEBHOOKS.md) for the answers.

| Case | Expected result |
|---|---|
| First state document save | The configured webhook delivers the initial observation. |
| Later status change | The receiver applies the new observation. |
| Unchanged host report | Central answers `no change` and advances only `last_reported_at`. |
| Invalid signature or unknown sender | Uniform rejection and no state write. |
| Repeated or older observation | Central answers `stale report` and does not regress state. |
| Report before the create response | Central drops it as `unknown server`. A repair read records the state later. |
| Sender failure after database commit | Repair reads recover the observation. |
| Delivery exhaustion | The failure is visible in Webhook Request Log and Central stays repairable. |
| VM deletion | A scoped API read confirms absence despite the missing state-row deletion event. |
| Sleeping VM reports stopped | No false shutdown, failure, or subscription cancellation. |

Verify first-save and change conditions on the deployed Framework, not only on a mocked document.

Configure retries explicitly. Verify the sender's scheduler and worker queue. A stored Webhook record alone does not prove delivery.

Do not require a new Atlas event queue. Repair reads (`central.integrations.servers.reconcile`, every 10 minutes) cover lost and unmatched reports.

## Server lifecycle tests

Use the approved Pilot and plain Ubuntu images. Check the readiness rule for each image type.

| Case | Expected result |
|---|---|
| Pilot server creation | Correct Team and VM credential, automatic admin URL, and successful Pilot login. |
| Ubuntu creation | Correct size and SSH key setup. No Pilot credential or Site record is required. |
| Access controls | Pilot controls appear only on a Pilot-managed server. Ubuntu shows supported SSH access information. |
| Explicit stop | Requested and observed state converge to stopped. Customer traffic does not wake it. |
| Start | Requested and observed state converge to running. |
| Restart | The action completes only after an observed change away from Running. A repeated running event is insufficient. |
| Delete | Confirmation, scoped absence check, credential revocation where applicable, and one billing effect. |
| Unknown response | The operation stays recoverable without blind creation or action retries. |
| Another Team | List, document, mutation, and Pilot login access are denied. |

Record the actual Ubuntu access path. A private mesh address alone does not establish customer SSH access.

## End-to-end sequence

1. Sign up as a customer and create the customer's Team.
2. Request one trial and confirm one VM and one prepared site.
3. Observe a signed state update and complete site login.
4. Create a separate Pilot server and open its admin from Central.
5. Create a plain Ubuntu server and verify its size and SSH access.
6. Stop, start, and restart each server type. Confirm the actual results.
7. Let the trial VM sleep while Central synchronization stays active.
8. Send customer traffic and confirm wake and site access.
9. Interrupt callback delivery and prove recovery through repair reads.
10. Use a second Team to verify denied access and operations.
11. Delete the test resources and confirm remote absence and credential cleanup.

Use agreed automatic DNS names, a resource budget, and disposable customer data. Record resource IDs for cleanup.

Test both warm and cold startup. Record latency as evidence, not as a guaranteed performance promise.

## Cargo tests

Cargo sends `service`, `status`, and `service_endpoint` to `central.api.state_delivery.receive` with `X-FC-Source: cargo`. Central registers Cargo itself after a health check. It sends its receiver URL and a fresh secret.

Run `central.tests.test_state_delivery` and `central.tests.test_cargo_enrollment`. On staging, verify `Available` and `Not Available` separately. Require an actual service endpoint and reject placeholder addresses. Verify that a registered Cargo can report without a new provisioning cycle.

## Rename and domain tests

Run `central.tests.test_site_domain` and `central.tests.test_sites`. On staging, track the returned Pilot task IDs through success and failure.

| Case | Evidence |
|---|---|
| Site rename | The new name works, Central Site identity stays stable, and old-name behavior matches the request. |
| Admin rename | The task succeeds and the management alias still reaches Pilot. |
| Domain attachment | Ownership is verified and the correct regional proxy map points to the VM. |
| Regional name HTTPS | The regional proxy terminates TLS and the public HTTPS request succeeds. |
| Custom domain HTTPS | Pilot holds a valid certificate, accepts PROXY protocol v2, and the public HTTPS request succeeds. |
| Domain failure | The error stays visible on the Site Domain. Retry or cleanup is safe. |
| Domain removal | The owned proxy route is removed without an effect on another domain. |
| Cross-Team claim | A second Team cannot take an existing or pending domain claim. |

A task acceptance response does not prove completion.

## Migration and handover

Test the actual staging source schema. Run required patches twice and verify identities and references.

Record backups, maintenance steps, validation results, and how to restore local data. A database restore does not reverse a remote VM operation.

Each PR records checks and unresolved dependencies. The staging report records the real journey results and any remaining blocker.

Do not put credentials, private keys, or raw credential metadata in fixtures, screenshots, delivery payloads, or PR descriptions.

## What does staging need?

Staging must have the matching Atlas schema and API, a verified region ID, Central key trust, a healthy Metal Server, available Pilot and Ubuntu System images, and working wildcard DNS. When these are ready, run creation, start, stop, Pilot access, Ubuntu access, and deletion with the same customer Team.

## Local connection notes

On macOS, start the local bench with `NO_PROXY='*' pilot start`. This prevents the Python system proxy lookup from stopping a forked background worker before an Atlas request is sent. This setting applies to the local development process only.

If a worker stops while an action is Dispatching, do not repeat creation based only on an empty VM list. Inspect the worker failure and check Atlas. Requeue only when evidence proves the request was not sent. Otherwise, use the uncertain-action resolution flow.

Staging Atlas does not return an automatic proxy hostname, so Central encodes the hostname label from the observed mesh address and the region's `proxy_domain`. Image maintenance belongs to Atlas and Cargo.
