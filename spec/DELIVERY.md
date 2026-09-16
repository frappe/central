# Central v0.2 delivery

## Purpose

Prioritize a working staging integration by Friday, September 18, 2026. Complete the wider rewrite after that milestone.

The deadline depends on one ready region, usable Pilot and Ubuntu images, DNS access, and review availability. Record an unmet dependency early. Do not trade authorization or data safety for the date.

Read [Scope](REWRITE_SCOPE.md) for ownership and contracts. Read [Validation](LOCAL_ENVIRONMENT.md) for required proof.

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

Configure one staging region, proxy, Cargo instance, Pilot and Ubuntu image profiles, and public Central callback URL. Verify region and tenant identity.

Add required Team tenant IDs, credentials, signer support, and patches. Preserve existing Asset, Atlas Instance, and billing identities.

Check affected token consumers. Reuse the existing dashboard and whitelisted API style. Do not introduce a new public API framework.

Acceptance:

- Existing Teams receive valid tenant IDs without changing verified remote ownership.
- Another Team cannot read or act on the test VM.
- Actual Atlas and Pilot accept Central tokens and reject invalid audiences.
- The Pilot profile records a verified shape, aliases, proxy mode, and runtime versions. The Ubuntu profile supports SSH key setup.
- Required data patches pass on populated data and on a fresh install.
- Region endpoints and credentials work without a new Central-to-region SSH tunnel.

## Friday phase 1: trial signup and state delivery

**Result:** A customer creates a trial and enters its site. The interface shows state changes from Framework webhooks.

Implement the thin Atlas create/read/delete adapter, metadata bootstrap, automatic names, Pilot readiness, and login. Reuse existing request and action records.

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
| 0C | Wednesday | Regional configuration and approved Pilot/Ubuntu image profiles. | Central can authenticate to the selected region and validate create inputs. |
| 1 | Wednesday into Thursday | Trial create, metadata bootstrap, state receiver, and site login. | One signup reaches one working site without duplicate VMs. |
| 2 | Thursday | Pilot and Ubuntu server creation, Open Pilot, and power actions. | Both server types complete their supported dashboard flows. |
| 3 | Thursday into Friday | Event recovery, Team isolation, migration rehearsal, and real staging proof. | The agreed journey passes on the prepared staging region. |

Stages 0A, 0B, and 0C are small PRs within phase 0. Wait for user review and commit approval before moving to the next stage. If the user asks to continue before a PR is merged, base the dependent branch on the approved commit and keep its changes uncommitted until its own review.

Use blr.atlas.localhost for local contract checks while the regional staging deployment is prepared. Repeat integration checks against staging when it is available.

These are target dates and dependency gates, not promised elapsed times. Record missing regional configuration and images as blockers early.

Cargo is available in the local bench for contract checks. Friday uses existing regional infrastructure and prepared images. New service ordering is deferred.

## After-Friday phases

| Phase | Result |
|---|---|
| 4 | Site/admin rename, domain ownership and routing, Pilot TLS, and Cargo backend registration. |
| 5 | Typed API core, OpenAPI, generated clients, target Server/Site/Region model, and image catalog with patches. |
| 6 | Resize and migration progress, console, snapshots, and fleet-scale recovery. |
| 7 | Services, live health, telemetry, IAM, partners, notifications, and dashboard standards review. |
| 8 | Full suite, complete migration rehearsal, regional acceptance, and release review for develop. |

Do not weaken the Friday implementation to create temporary generic abstractions. Extend its domain-owned code in later phases.

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
| Image metadata | Supply verified Pilot and Ubuntu profiles. Do not wait for the full catalog API. |
| Atlas callback setup | Verify the document event, condition, shared secret, scheduler, and delivery log. |
| Framework retry revision | Pin deployed Framework behavior and configure retries. Keep repair reads even when retries exist. |
| Pilot access | Verify automatic admin routing, token audience, and bootstrap on the selected image. |
| Ubuntu access | Verify SSH key injection and an operator-approved network path for the customer. |
| Restart result | Verify a completion signal or add the smallest required Atlas contract. |
| Trial policy | Confirm size, idle timeout, limits, and whether scheduled work may pause during sleep. |
| Unknown create | Provide an operator recovery action until remote idempotency or lookup is proven. |
