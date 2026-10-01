# Central delivery

## Purpose

This document lists the open delivery work after the v0.2 baseline, in priority order, and the gate that proves it on a real region. Do not trade authorization or data safety for speed.

Read [Scope](REWRITE_SCOPE.md) for ownership and contracts. Read [Validation](LOCAL_ENVIRONMENT.md) for required proof.

## What is the current baseline?

v0.2 is the shipped baseline. It merged into `develop` in #393. New work branches from `develop` and opens a PR into `develop`. Nothing below is proved on the staging region yet.

| Stage | State | Remaining |
|---|---|---|
| Team tenant identity | Done | |
| Atlas signing and Pilot authentication | Done | |
| Regional configuration and image offerings | Done | |
| Trial signup | Partial | The flow works end to end. Readiness uses a direct site probe. A trial has no product identity, so a CRM or ERPNext trial looks the same as a plain one. |
| State delivery | Partial | The signed Atlas and Cargo receivers work. Central orders Atlas reports by the region's `observed_at`, stored as `Virtual Machine.last_reported_at`. Durable receipts, payload digest deduplication, and retry of an unmatched report do not exist. |
| Server creation and lifecycle | Done | Create, start, stop, restart, terminate, resize, and Open Pilot work. Creation sends the idle sleep policy. |
| Custom domains | Done | A Pilot registers its site and custom domains through `central.api.pilot`. Central verifies a TXT record, and a CNAME for a non-apex name, before it creates the route. |
| Site and admin rename | Done | Central asks Pilot to rename the trial site (`Site.apply_subdomain`) and the admin domain (`VirtualMachine.claim_admin_hostname`). |
| Cargo registration | Done | Central registers each region's Cargo connection itself. |
| Staging proof | Not started | |

`Region` carries the Atlas connection (`base_url`, `atlas_region_id`, `proxy_domain`, `webhook_secret`, and signed-access health fields) and the Cargo connection (`cargo_base_url`, `cargo_status`, `cargo_registered_at`, and `cargo_webhook_secret`) through separate controller mixins. A regional read uses one record. A Pilot-registered Site Domain resolves its `Site` from the credential's Virtual Machine.

## What are the known gaps?

- A snapshot of a Pilot server cannot be restored. Pilot applies its first-boot setup only once, so a restored disk keeps the old server's identity. See [VM snapshots](../central/infrastructure/doctype/vm_snapshot/SPEC.md#restore).
- Restart completion has no authoritative signal from the region. Resource Action waits for one observed state change away from Running before Running can complete the action. An upstream restart-completion contract is open.

## What work remains, in order?

Each item is one PR into `develop` unless it says otherwise.

### 1. Product trials

**Result:** an ERPNext trial and a CRM trial each look like their own product. This blocks sending customers a product-specific link.

`product` reaches the signup page (`VerifyEmailPage.vue`) as a query parameter and stops there. The backend never sees it.

- Carry `product` from signup through to `create_trial_site` and store it on the `Resource Action` and the `Site`.
- Add `product` to `SIGNUP_IMAGE_TAGS` so the region selects that product's prepared image.
- Show the product's logo, name, and wording on the signup, naming, and ready pages.
- Refuse a product with no enabled offering, with a readable message.

### 2. State delivery hardening

**Result:** no report is lost or replayed. Do this before the staging proof, because a proof run would otherwise find these gaps late.

- Store a receipt before Central replies `queued`. Today only a queue holds the work, and the ten-minute reconcile finds a lost job.
- Deduplicate by payload digest. The `no change` and `stale report` checks catch a repeat of the current state and an older report. They do not catch a replayed sequence with new timestamps.
- Retain an unmatched report. Central drops a report for a machine it does not own yet as `unknown server`. Retain it and match it when the creation settles.

### 3. Model cleanup

**Result:** the records match the way the product talks about them. Each schema change includes its data patch and focused tests.

- Hide a server that carries a trial site from the trial customer. A trial customer owns a site, not a server, and must not see both.

### 4. Product rules

- Increase the wildcard-domain suffix length allowed on the onboarding naming page (`dashboard/src/pages/onboarding/SiteNamePage.vue`), and widen the field to fit it.
- Find where the Frappe `Asia/Calcutta` timezone comes from. `central/www/dashboard.py` maps it to `Asia/Kolkata` today.

### 5. Staging proof

**Result:** the agreed customer journey works on the real staging region, not only in tests.

Hold this until items 1 and 2 land. Acceptance:

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

## PR rules

Each PR includes changed behavior, required patches, focused tests, matching UI changes, and current documentation.

Keep remote calls in integrations and authorization in Central IAM. Enforce list and document permissions. Follow the Desk and error-handling rules in CLAUDE.md.

Review every changed line before committing. Use the repository's commit and PR format. Do not add co-author or agent metadata.

Record any failed check and whether it is a baseline issue. Do not mass-format unrelated code.

Documentation-only PRs require content, link, conflict-marker, and diff checks. Implementation PRs use the validation commands in CLAUDE.md.
