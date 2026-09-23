# Central v0.2 delivery

## Purpose

Reach a working staging integration for trial signup and the server lifecycle, then continue the wider rewrite.

The Friday, September 18, 2026 target has passed. Signup and server lifecycle now work end to end, at a bare minimum, and Atlas and Pilot have landed supporting work of their own since. The remaining work below has no new fixed date. Do not trade authorization or data safety for speed.

Read [Scope](REWRITE_SCOPE.md) for ownership and contracts. Read [Validation](LOCAL_ENVIRONMENT.md) for required proof.

## Current status

Updated 2026-09-21, after fetching `upstream/v0.2` in Central, `upstream/develop` in Atlas, and `upstream/develop` in Pilot. `Done` means the behavior exists in this branch. `Partial` names what is still missing. Nothing below is proved on the staging region yet.

| Stage | State | Remaining |
|---|---|---|
| 0A Team tenant identity | Done | |
| 0B Atlas signing and Pilot authentication | Done | The `pilot-central` metadata carries `initial_jwks_cache`. Pilot hardened its own bootstrap JWKS verification since (`frappe/pilot#509`). |
| 0C Regional configuration and image offerings | Done | |
| 1 Trial signup | Partial | The flow works end to end, including readiness by a direct site probe instead of a wait on a state report. It still carries no product identity, so a CRM or ERPNext trial looks the same as a plain one. |
| 1 State delivery | Partial | The signed Atlas and Cargo receivers work. Durable receipts, region event ordering, payload digest deduplication, and retry of an unmatched report do not exist. |
| 2 Server creation and lifecycle | Done | Create, start, stop, restart, terminate, resize, and Open Pilot work. Creation sends the idle sleep policy. |
| 3 Staging proof | Not started | |

A Pilot-registered Site Domain resolves its `Site` from the credential's Asset, so the two producers of a route agree. A trial's readiness no longer waits for a state report: the `Site` record is created as soon as the machine has an address, and it reads ready once the site answers its own ping. `Atlas Instance` and `Cargo Instance` are both gone: `Region` now carries the Atlas connection (`base_url`, `atlas_region_id`, `proxy_domain`, `webhook_secret`, the signed-access health fields) and the Cargo connection (`cargo_base_url`, `cargo_status`, `cargo_registered_at`, `cargo_webhook_secret`) as two clearly separated halves of one record — mixed in from `atlas_connection.py` and `cargo_connection.py` in the doctype's own folder, so the two never blur into one pile of fields and logic. A regional read is one record, not three.

Work that landed ahead of its phase: proxy site and custom domain routes, the Pilot rename helpers, the Cargo report receiver, Pilot-driven domain registration with DNS ownership checks, one regional telemetry token for logs and metrics, and, in Pilot itself, renamed-site token binding and route resolution by hostname (`frappe/pilot#513`).

Phase 4 is therefore part done. A Pilot registers its own site and custom domains through `central.api.pilot`, and Central verifies a TXT record, and a CNAME for a non-apex name, before it creates the route. Site rename and TLS stay with Pilot. Central does not drive them.

### Deferred by design, still open

These were removed from the staging milestone on purpose. They are the next structural work.

### Known gaps outside the phase list

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

Review the [operation contract](../central/infrastructure/doctype/resource_action/SPEC.md), the [image catalog](../central/infrastructure/doctype/image_offering/SPEC.md), and [test coverage](CUTOVER_TEST_COVERAGE.md). Review and merge this phase before beginning signup and Framework webhooks. Do not commit without the user's approval.

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

Custom domains and Cargo backend registration follow the Friday milestone. Site rename, admin-domain rename, and TLS stay with Pilot.

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

## Remaining work, in order

The Friday target has passed and the critical journey works at a bare minimum. This replaces the day-by-day schedule with a plain priority order for what is left. Each item is one PR into `v0.2` unless it says otherwise.

### 1. Product trials

**Result:** an ERPNext trial and a CRM trial each look like their own product. This is the most visible gap now that signup itself works, and blocks sending customers a real product-specific link.

`product` reaches the signup page as a query parameter and stops there. The backend never sees it.

- Carry `product` from signup through to `create_trial_site` and store it on the `Resource Action` and the `Site`.
- Add `product` to `SIGNUP_IMAGE_TAGS` so the region selects that product's prepared image.
- Show the product's logo, name, and wording on the signup, naming, and ready pages.
- Refuse a product with no enabled offering, with a readable message.

### 2. State delivery hardening

**Result:** no report is lost, replayed, or applied out of order. Do this before staging proof, not after: it is exactly what a proof run would otherwise catch late.

- Order by the region's own event time, not by Central's arrival time. `apply_atlas_report` stamps `now_datetime()`, so two reports processed out of order can regress state. Carry the region's timestamp in the payload and pass it to `record_observed_state`.
- Store a receipt before replying `queued`. Today the reply promises work that only a queue holds, and a lost job is found only by the ten-minute reconcile.
- Deduplicate by payload digest. The `no change` short-circuit catches a repeat of the current state. It does not catch a replayed A to B to A.
- Retain an unmatched report. A report for a machine Central does not own yet is dropped as `unknown server`. Retain it and match it when the creation settles.

### 3. Region self-enrolment

**Result:** an operator adds a region without editing two sites by hand.

- Add a **Configure Deliveries** action on `Atlas Instance`. It calls `PUT /api/atlas/webhooks` with Central's receiver URL, the stored `webhook_secret`, and `enabled`. It records the result on the record, like Test Connection does.
- Cargo needs the matching route before its half can work. Until it exists, keep the Cargo secret manual and say so on the record.
- Remove `db_set` from the Atlas `VM State` doctype, so it only raises events. This is Atlas-side work.

### 4. Model cleanup

**Result:** the records are named and shaped the way the product talks about them.

Do this as separate PRs, each with its patch, and after item 1 lands.

- Renamed `Asset` to `Virtual Machine` — done, via `frappe.rename_doc` and a patch. `cluster` stays the field name for now — renaming it to `region` would touch the doctype a second time right after this rename touched it once.
- Merged `Atlas Instance` and `Cargo Instance` into `Region` — done. Every regional read is one record now, each service behind its own mixin (`atlas_connection.py`, `cargo_connection.py`) so the two stay separated in code and never share a field, and both merge patches carried existing connection data across losslessly.
- Link `Site` to its machine and hide a machine that carries a site. A trial customer owns a site, not a VM, and should not see both.
- Split Central's doctypes out of the one flat `Central` module into `Identity`, `Provisioning` (Asset/Virtual Machine, Resource Action, Region, Image Offering, Site, Site Domain), `Credentials`, and a slimmer `Central`. This is what gives the Desk sidebar the same grouped navigation Atlas has, for free, via Frappe's own per-module tree — no custom sidebar code. Do this once the doctypes above reach their final names, so nothing moves folders twice. Add a Number Card dashboard to Central's own workspace at the same time (servers by status, sites, stuck Resource Actions, regions) — today it holds only IAM shortcuts.

### 5. Product rules and cleanup

- Delete `Central Tunnel Settings`, `Connect Credential`, and `Passport Registration`, with a patch each. Nothing reads them.
- Increase the wildcard-domain suffix length allowed in New Site, and widen that dialog to fit it.
- Confirm the Frappe `Asia/Calcutta` timezone fault and where it comes from.

### 6. Staging proof

**Result:** the agreed customer journey is proved on the real staging region, not just in tests.

Hold this until items 1 through 3 land: proving the journey before state delivery is hardened would just rediscover the same gaps by hand. Use the acceptance list already in [Friday phase 3](#friday-phase-3-staging-proof).

## PR rules

Each PR includes changed behavior, required patches, focused tests, matching UI changes, and current documentation.

Keep remote calls in integrations and authorization in Central IAM. Enforce list and document permissions. Follow the Desk and error-handling rules in CLAUDE.md.

Review every changed line before committing. Use the repository's commit and PR format. Do not add co-author or agent metadata.

Record any failed check and whether it is a baseline issue. Do not mass-format unrelated code.

Documentation-only PRs require content, link, conflict-marker, and diff checks. Implementation PRs use the validation commands in CLAUDE.md.
