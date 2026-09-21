# Central v0.2 delivery

## Purpose

Prioritize a working staging integration by Friday, September 18, 2026. Complete the wider rewrite after that milestone.

The deadline depends on one ready region, usable Pilot and Ubuntu images, DNS access, and review availability. Record an unmet dependency early. Do not trade authorization or data safety for the date.

Read [Scope](REWRITE_SCOPE.md) for ownership and contracts. Read [Validation](LOCAL_ENVIRONMENT.md) for required proof.

## Current status

Updated 2026-09-21, after pulling `upstream/v0.2` and reading the code. `Done` means the behavior exists in this branch. `Partial` names what is still missing. Nothing below is proved on the staging region yet.

| Stage | State | Remaining |
|---|---|---|
| 0A Team tenant identity | Done | |
| 0B Atlas signing and Pilot authentication | Done | The `pilot-central` metadata now carries `initial_jwks_cache`. |
| 0C Regional configuration and image offerings | Done | |
| 1 Trial signup | Partial | The flow works end to end. It carries no product identity, so a CRM or ERPNext trial looks the same as a plain one. |
| 1 State delivery | Partial | The signed Atlas and Cargo receivers work. Durable receipts, region event ordering, payload digest deduplication, and retry of an unmatched report do not exist. |
| 2 Server creation and lifecycle | Done | Create, start, stop, restart, terminate, resize, and Open Pilot work. Creation sends the idle sleep policy. |
| 3 Staging proof | Not started | |

A Pilot-registered Site Domain now resolves its `Site` from the credential's Asset, so the two producers of a route agree.

Work that landed ahead of its phase: proxy site and custom domain routes, the Pilot rename helpers, the Cargo report receiver, Pilot-driven domain registration with DNS ownership checks, and one regional telemetry token for logs and metrics.

Phase 4 is therefore part done. A Pilot registers its own site and custom domains through `central.api.pilot`, and Central verifies a TXT record, and a CNAME for a non-apex name, before it creates the route. Central-driven rename and TLS coordination remain.

### Deferred by design, still open

These were removed from the staging milestone on purpose. They are the next structural work.

- `Asset` is still named `Asset`. The product name is Virtual Machine.
- `Atlas Instance` and `Region` are still two records. `Region` holds geography and `Atlas Instance` holds the connection, and every regional read goes through `Atlas Instance`.
- Signup readiness still waits for the region to report `Running` before it probes the site.

### Known gaps outside the phase list

- A terminated server keeps its Site Domain routes. Only its Pilot credentials are revoked.
- Central cannot enrol a region. Atlas accepts `PUT /api/atlas/webhooks`, so the receiving half exists and Central never calls it. Cargo has no such route at all, and its Central URL and secret are typed into Cargo Settings by hand.
- Resize accepts a disk change. The agreed product rule is CPU and memory only.
- `Central Tunnel Settings`, `Connect Credential`, and `Passport Registration` have no reader in this app or its siblings.

## Branch workflow

```text
develop
  +-- v0.2
        ^-- feature/v0.2-phase-0-tenant-identity reviewed PR, stage 0A
        ^-- phase 0 signing PR                  reviewed PR, stage 0B
        ^-- phase 0 configuration PR            reviewed PR, stage 0C
        ^-- feature/v0.2-phase-1-trial-state     reviewed PR
        ^-- feature/v0.2-phase-2-server-lifecycle reviewed PR
        ^-- feature/v0.2-phase-3-staging-proof   reviewed PR
        ^-- later rewrite phases

user merges accepted v0.2 -> develop
```

Each phase starts from the latest accepted v0.2. Each PR targets v0.2. Split a phase into smaller review units when needed.

At the end of each stage, leave the changes uncommitted for user review. Commit and push only after the user approves that stage. The user merges each PR into v0.2 and controls the final merge into develop. Preserve the old branch as reference. PR #321 is closed. The agreed plan is committed directly on v0.2. GitHub marked PR #322 merged when v0.2 received its commits.

Reuse correct code only after checking it against the selected source revisions and existing data. Do not cherry-pick the earlier foundation wholesale.

## Friday phase 0: configuration and minimum identity

**Result:** Central can authenticate to the selected Atlas and Pilot deployment.

Configure one staging region, proxy, Cargo instance, Pilot and Ubuntu image offerings, and public Central callback URL. Verify region and tenant identity.

Add required Team tenant IDs, credentials, signer support, and patches. Preserve existing Asset, Atlas Instance, and billing identities.

Check affected token consumers. Reuse the existing dashboard and whitelisted API style. Do not introduce a new public API framework.

Acceptance:

- Existing Teams receive valid tenant IDs without changing verified remote ownership.
- Another Team cannot read or act on the test VM.
- Actual Atlas and Pilot accept Central tokens and reject invalid audiences.
- Image offerings select regional System images by tags. Cargo's Pilot image includes a prepared site for both server creation and signup. Obtain tested sizes from the image contract before provisioning.
- Required data patches pass on populated data and on a fresh install.
- Region endpoints and credentials work without a new Central-to-region SSH tunnel.

### Current phase 0 review scope

This PR includes the signed Atlas client, on-demand regional image selection, whole-CPU plan selection, and the server creation interface. Resource Action is the single operation record. It saves validated intent before dispatch and recovers accepted operations through scoped reads. Start, stop, and termination use the same record. The accepted billing quote survives catalog changes while an action waits.

Review the [operation contract](../central/central/doctype/resource_action/SPEC.md), the [image catalog](../central/central/doctype/image_offering/SPEC.md), and [test coverage](CUTOVER_TEST_COVERAGE.md). Review and merge this phase before beginning signup and Framework webhooks. Do not commit without the user's approval.

## Friday phase 1: trial signup and state delivery

**Result:** A customer creates a trial and enters its site. The interface shows state changes from Framework webhooks.

Use the signed Atlas adapter and Resource Action from phase 0. Add prepared-site discovery, signup naming, Pilot readiness, and site login. Use Resource Action as the only operation record.

Configure Atlas's Virtual Machine State Framework webhook. Add the signed Central receiver, durable receipt processing, and the minimum shared state writer.

Add bounded action checks and a low-frequency repair scan. Include deletion cleanup and credential revocation before calling the trial flow complete.

Acceptance:

- One accepted signup request creates one VM and uses the prepared site's existing data.
- Repeated submissions and uncertain create responses cannot silently create duplicate VMs.
- An event arriving before the create response is retained and later matched correctly.
- The receiver rejects bad signatures and unknown sources.
- Duplicate or older events cannot repeat side effects or regress state.
- A running VM is followed by successful site readiness and login.
- A missed event or stopped worker recovers through receipts or a scoped API read.
- Confirmed deletion revokes the credential and applies required billing effects once.
- The dashboard shows a useful error or unknown outcome instead of waiting forever.

## Friday phase 2: server creation and lifecycle

**Result:** A customer can create a Pilot server, open Pilot, and create a plain Ubuntu server.

Reuse the Atlas adapter, identity, and state handling from phases 0 and 1. Add explicit image choices and readiness rules.

Connect start, stop, restart, and delete to the current Atlas API. Track each action separately from the last observed VM state.

Acceptance:

- A Pilot server receives its own credential and opens the correct Pilot admin through Central.
- A plain Ubuntu server receives the requested approved size and SSH keys.
- Offer only plans with positive whole-vCPU counts. Remove fractional steps from custom configurations and reject fractional CPU requests without rounding.
- Ubuntu creation does not wait for Pilot or create a Site record.
- The interface shows supported access information and hides Pilot controls for Ubuntu.
- Start and stop reach the requested state. Customer traffic cannot wake an explicitly stopped VM.
- Restart uses an authoritative completion signal. A running state alone cannot finish the action.
- Delete requires confirmation and completes only after a correctly scoped absence check.
- Deletion revokes Pilot credentials where applicable and applies existing billing effects once.
- Duplicate requests, remote errors, and uncertain responses leave a recoverable action record.
- Another Team cannot read, control, delete, or open Pilot for the server.

## Deferred integration work

Site rename, admin-domain rename, custom domains, TLS coordination, and Cargo backend registration follow the Friday milestone.

Their verified contracts and known gaps remain in [Scope](REWRITE_SCOPE.md). They must not block signup or the required server lifecycle.

## Friday phase 3: staging proof

**Result:** The agreed customer journey works on the real staging region.

Freeze the milestone scope after the critical journey works. Spend the remaining time on integration faults, failure recovery, migration rehearsal, and handover.

Acceptance:

- Run signup and site login through the supported UI.
- Create a Pilot server and open its admin.
- Create a plain Ubuntu server and verify SSH access through the supported network.
- Exercise start, stop, restart, and delete for both server types.
- Observe an idle VM sleep while Central synchronization stays active.
- Wake the VM with customer traffic and confirm the site works.
- Stop a receiver worker or reject a delivery, then prove eventual recovery.
- Replay duplicate and older signed events and verify no repeated effects.
- Verify two Teams cannot read, mutate, or access each other's resources.
- Run focused tests, affected billing tests, dashboard checks, and the required build.
- Rehearse changed data patches on representative staging data.
- Record dependency revisions, results, remaining defects, and operator recovery steps.

A VM running event, a green unit test, or a successful API response alone does not satisfy this gate.

## Work order for the deadline

Aim to complete implementation on Wednesday and Thursday. Reserve Friday for final verification and fixes, not the first integration run.

| Stage | Target | Work | Exit condition |
|---|---|---|---|
| 0A | Wednesday first | Team tenant identity, allocation, and populated-data patch. | IDs are unique and immutable. Ambiguous existing ownership blocks migration. |
| 0B | Wednesday | Atlas signing, Pilot authentication, and consumer verification. | Real local verifiers accept the intended tokens and reject wrong audiences. |
| 0C | Wednesday | Regional configuration, image offerings, and on-demand Atlas discovery. | Central can authenticate to the region and discover available shared builds. |
| 1 | Wednesday into Thursday | Trial create, metadata bootstrap, state receiver, and site login. | One signup reaches one working site without duplicate VMs. |
| 2 | Thursday | Pilot and Ubuntu server creation, Open Pilot, and power actions. | Both server types complete their supported dashboard flows. |
| 3 | Thursday into Friday | Event recovery, Team isolation, migration rehearsal, and real staging proof. | The agreed journey passes on the prepared staging region. |

Stages 0A, 0B, and 0C are small PRs within phase 0. Wait for user review and commit approval before moving to the next stage. If the user asks to continue before a PR is merged, base the dependent branch on the approved commit and keep its changes uncommitted until its own review.

Use blr.atlas.localhost for local contract checks while the regional staging deployment is prepared. Repeat integration checks against staging when it is available.

These are target dates and dependency gates, not promised elapsed times. Record missing regional configuration and images as blockers early.

Cargo is available in the local bench for contract checks. Friday uses existing regional infrastructure and prepared images. New service ordering is deferred.

## Work after the staging milestone

Ordered by what unblocks the most. Each item is one PR into `v0.2` unless it says otherwise.

### 1. Signup latency: readiness by probe, not by callback

**Result:** a trial reaches its site without waiting for an Atlas state report.

Atlas derives a VM's mesh address from its region, tenant, and number, so the address is known the moment creation is accepted. `_finalize` already reads the machine back once. Therefore Central can name the site and the Pilot gateway immediately, and it never needs a report to learn where to knock.

- Create the `Site` record from the creation read instead of from `observe_server` alone, so a trial has an address before any report lands.
- Drop `status == "Running"` as the gate in `site_state` and `Site.get_pilot_access`. Readiness becomes: the site answers its ping, or Pilot answers its health endpoint. A machine that answers is running, whatever the mirror says.
- Keep the state reports. They still drive the mirror, the console badges, and `Resource Action`, and they now run behind the customer instead of in front of them.
- Bound the probe. Give it a short timeout and a stop condition, so a dead machine fails with a message instead of polling forever.

Acceptance: a signup on staging reaches the site in under 10 seconds with the state webhook disabled.

### 2. Product trials

**Result:** an ERPNext trial and a CRM trial each look like their own product.

`product` reaches the signup page as a query parameter and stops there. The backend never sees it.

- Carry `product` from signup through to `create_trial_site` and store it on the `Resource Action` and the `Site`.
- Add `product` to `SIGNUP_IMAGE_TAGS` so the region selects that product's prepared image.
- Show the product's logo, name, and wording on the signup, naming, and ready pages.
- Refuse a product with no enabled offering, with a readable message.

### 3. Region self-enrolment

**Result:** an operator adds a region without editing two sites by hand.

- Add a **Configure Deliveries** action on `Atlas Instance`. It calls `PUT /api/atlas/webhooks` with Central's receiver URL, the stored `webhook_secret`, and `enabled`. It records the result on the record, like Test Connection does.
- Cargo needs the matching route before its half can work. Until it exists, keep the Cargo secret manual and say so on the record.
- Remove `db_set` from the Atlas `VM State` doctype, so it only raises events. This is Atlas-side work.

### 4. State delivery hardening

**Result:** no report is lost, replayed, or applied out of order.

- Order by the region's own event time, not by Central's arrival time. `apply_atlas_report` stamps `now_datetime()`, so two reports processed out of order can regress state. Carry the region's timestamp in the payload and pass it to `record_observed_state`.
- Store a receipt before replying `queued`. Today the reply promises work that only a queue holds, and a lost job is found only by the ten-minute reconcile.
- Deduplicate by payload digest. The `no change` short-circuit catches a repeat of the current state. It does not catch a replayed A to B to A.
- Retain an unmatched report. A report for a machine Central does not own yet is dropped as `unknown server`. Retain it and match it when the creation settles.

### 5. Model cleanup

**Result:** the records are named and shaped the way the product talks about them.

Do this as separate PRs, each with its patch, and after items 1 and 2 land.

- Rename `Asset` to `Virtual Machine`. It is a mechanical rename with a wide reach: 74 Python files and 12 doctype JSON files refer to it. Use `frappe.rename_doc` on the DocType and a patch for the links.
- Merge `Atlas Instance` into `Region`. One region is one endpoint, one proxy zone, one numeric Atlas ID, and one secret. Two records for one thing is what makes the code say `cluster` in one place and `region` in another.
- Link `Site` to its machine and hide a machine that carries a site. A trial customer owns a site, not a VM, and should not see both.

### 6. Product rules and cleanup

- Resize must offer CPU and memory only. Remove the disk change from `resize_server`, the API, and the console.
- Remove a terminated server's Site Domain routes, or refuse termination while a site still holds a route.
- Delete `Central Tunnel Settings`, `Connect Credential`, and `Passport Registration`, with a patch each. Nothing reads them.

### 7. Pilot and domain remainders

Reported from staging use and not yet verified in code.

- The admin domain serves `http` behind the proxy. Pilot needs to be told it is behind TLS termination.
- A site needs `clear-cache` before its in-app cloud window shows the new URL.
- TLS for a non-wildcard custom domain needs a rework.
- The new-site modal is too narrow for a long wildcard suffix.
- Confirm the Frappe `Asia/Calcutta` timezone fault and where it comes from.

## PR rules

Each PR includes changed behavior, required patches, focused tests, matching UI changes, and current documentation.

Keep remote calls in integrations and authorization in Central IAM. Enforce list and document permissions. Follow the Desk and error-handling rules in CLAUDE.md.

Review every changed line before committing. Use the repository's commit and PR format. Do not add co-author or agent metadata.

Record any failed check and whether it is a baseline issue. Do not mass-format unrelated code.

Documentation-only PRs require content, link, conflict-marker, and diff checks. Implementation PRs use the validation commands in CLAUDE.md.

## Dependencies that can block Friday

| Dependency | Required action |
|---|---|
| Test region and DNS | Identify the operator, region, automatic DNS names, and access before phase 0 starts. |
| Image metadata | Use Atlas System image discovery. Expose snapshot shape and tested resource requirements before plan eligibility and provisioning. |
| Atlas callback setup | Verify the document event, condition, shared secret, scheduler, and delivery log. |
| Framework retry revision | Pin deployed Framework behavior and configure retries. Keep repair reads even when retries exist. |
| Pilot access | Verify automatic admin routing, token audience, and bootstrap on the selected image. |
| Ubuntu access | Verify SSH key injection and an operator-approved network path for the customer. |
| Restart result | Verify a completion signal or add the smallest required Atlas contract. |
| Trial policy | Confirm size, idle timeout, limits, and whether scheduled work may pause during sleep. |
| Unknown create | Met. Central looks the machine up by its action marker, so an unanswered creation settles itself. |
