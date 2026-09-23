# Central v0.2 simplification plan

## Purpose

Deliver one PR into `v0.2`, in ordered phases with reviewable commits. Simplify the code that runs today, correct defects, and make domain operations usable by the console and a future SaaS API. This document defines proposed work. Current behavior stays in the module specifications.

The assessment uses the working tree on 2026-09-23, including the existing dashboard backlog. Findings come from source inspection unless a check is explicitly named. Reproduce defects with focused tests before fixing them. Old line counts and test totals are not acceptance evidence.

Follow [CLAUDE.md](../CLAUDE.md), the [specification router](README.md), and each affected module's `SPEC.md`. Approve this plan before implementation. Update phase completion and newly discovered work here.

## Scope

- Review all non-billing Central code: identity, authorization, authentication, infrastructure, provisioning, integrations, services, notifications, APIs, controllers, hooks, jobs, setup code, tests, and the dashboard.
- Limit `central/billing/**` edits to required access fixes, provisioning and resize entry points, resource references, and notification delivery touched by this work. Preserve pricing, credits, ledger, tax, invoices, payments, and projections.
- Keep the requested dashboard consolidation, including billing screens. Moving fetching and presentation does not authorize a billing-domain rewrite.
- Use Atlas as a clarity reference. Keep Central's responsibilities in Central. Changes to Atlas, Pilot, Cargo, Connect, or Passport contracts require an explicit decision.
- Prepare typed, transport-independent operations and clear API contracts. A public API release, router, SDK, documentation generator, new authentication scheme, and capability-version change are outside this PR.

## What counts as simplification?

1. Delete duplicate decisions, queries, stale state, dead paths, and forwarding layers first. Search callers, hooks, jobs, and external consumers before deleting an entry point.
2. Use one function with explicit arguments when several functions perform the same operation. Keep separate operations when permission, transaction, retry, or completion rules differ. Do not introduce a generic workflow engine.
3. Put invariants and lifecycle behavior on the owning controller. Keep remote calls in `central/integrations/`. Routes validate, authorize, call the owner, and return a defined response.
4. Reuse Frappe APIs, Query Builder, lifecycle hooks, enqueue-after-commit, and existing decorators. Use decorators for repeated authorization or authentication with visible arguments and preserved signatures. Keep business transitions explicit.
5. Reduce how many places a reader must inspect to understand one operation. Extract only to remove duplication or give coherent behavior one owner. File length alone does not justify a split.
6. Preserve validation, tenant checks, locks, cleanup, and recovery. Line reduction is evidence, not a quota. Docstring and naming edits accompany substantive work.

## Order and completion gates

| Phase | Result | Gate before continuing |
|---|---|---|
| 0. Baseline | Scope inventory, focused reproductions, and recorded test/tooling failures. | Working journeys and failure cases are named; existing failures are distinguished from regressions. |
| 1. Access and API boundaries | One IAM decision path and corrected access defects. | Denial, cross-team, cross-user, and HTTP-method tests pass. |
| 2. Server and site operations | One action owner, common dispatch, explicit recovery, and durable resize. | Lifecycle, concurrency, uncertain-outcome, and billing integration tests pass. |
| 3. Remaining domain ownership | Simpler observation, services, credentials, notifications, and recovery. | Repeated jobs and callbacks do not duplicate effects; failures remain visible and recoverable. |
| 4. Dashboard | Thin pages, coherent composables, shared primitives, and correct request lifetimes. | Type, lint, build, and changed customer journeys pass. |
| 5. Closure | Consistent schema, documented contracts, safe patches, and full regression evidence. | Every inventory area is resolved or explicitly deferred; final checks and review are complete. |

These are phases inside one PR, not separate PRs. Urgent fixes can be early commits. Establish frontend checks in phase 0. Update types and consumers in the phase that changes their contract, not at the end.

## Phase 0: establish the baseline

**Completed on 2026-09-23.** The full Central suite passed 1,634 tests with one skipped. Patch registration passed with 60 listed patches and five known orphans. The dashboard production build passed with Tailwind-directive and chart-chunk warnings. Type checking fails while traversing the pinned Frappe UI source. Ruff reports 17 duplicate entries in `central/billing/revenue/invoicing/__init__.py`. The dashboard build produced no tracked changes. Live Resource Action metadata matches the repository and has no field for raw diagnostics yet.

Read implementation and specifications together. Track the following areas here as work proceeds. Each needs a concrete simplification, a correction, or a short reason to keep it. Do not treat the largest files as the entire scope.

| Area | Starting points | Review focus |
|---|---|---|
| Identity and access | `central/iam.py`, `permissions.py`, `utils/guards.py`, `identity/`, `users.py` | Duplicate policy, team resolution, cache invalidation, controller invariants, query and document permissions. |
| Authentication and tokens | `central/api/auth.py`, `api/pilot.py`, `api/sso.py`, `sso.py`, signing settings, Pilot Credential | OTP lifecycle, throttling, replay protection, audiences, secret handling, shared signing operations. |
| Resource lifecycle | `central/server_provisioning.py`, `resource_actions.py`, `site_provisioning.py`, `server_models.py`, infrastructure controllers | Intent, reservation, dispatch, observation, completion, retry, snapshots, domains. |
| Integrations | `central/integrations/`, Region connection modules | Client construction, response validation, errors, webhook ordering, bounded recovery. |
| Services and partners | `central/services/`, storage/Cargo clients, Team partner methods | Repeated provision/rotate/delete behavior, credential ownership, remote call placement. |
| Notifications and errors | `central/notification/`, `errors.py`, affected billing delivery calls | Event ownership, read markers, delivery outcomes, safe diagnostics. |
| Console | `dashboard/src/`, tooling and CI | Fetch ownership, state, mutations, permissions, types, design-system use. |
| Operations and tests | `central/hooks.py`, setup/demo code, patches, fixtures, `central/tests/`, `e2e/` | Dead paths, Desk operation, hook targets, test isolation, migration safety. |

- Record the full Central suite and dashboard type/lint/build baseline. Re-run historical failures. Imported Frappe UI source currently reports more than missing icon declarations; preserve the pinned version and application checks. Adding `exclude` is not proof that imported dependency source is fixed.
- Before rewriting lifecycle code, cover accepted creation, duplicate submission, uncertain acceptance, local finalization failure, recovery, retry, and existing billing effects. Add each bug's failing regression with its fix.
- Use test-owned disposable records. Check cleanup helpers such as `test_atlas_register._wipe`, global-count assertions, fixed future dates, and explicit commits. Do not delete unrelated site data to make tests pass.
- Record existing failures with their cause and owner. Fix isolation in scope. Do not weaken assertions or expand into unrelated billing repairs to obtain a green report.

## Phase 1: correct access and API boundaries

### Fix the demonstrated gaps

| Source finding | Change and regression case |
|---|---|
| `integrations/servers.py` omits restart from its capability map; `resource_actions.py` has another map. | Give command capability selection one owner. Process a queued restart through the actual worker path. |
| `billing/api/dashboard/account.py:list_switchable_teams` enumerates teams and billing details without a caller scope. | Remove the POC endpoint if unused; otherwise scope it to authorized teams or its intended operator audience. Correct the whitelist-boundary test. |
| User Notification Preference grants customer access without owner query and document hooks. | Enforce the row's user on list, direct read, create, and write. Test attempts to change the owner. |
| `iam.get_user_team_names` returns one row per membership role. | Return distinct teams. A user with two roles in one team must still resolve one default team. |
| Both `ServersPage.vue` and `ServerRowActions.vue` use power permission for resize. | Add and use `server:resize` consistently. Test users who have only one of these capabilities. |
| `api/sites.get_site` requires `server:view` but calls `site_state` with login enabled, creating an Administrator session. | Keep `server:view` as the view-and-open permission. Separate status reads from login mutation so polling does not create sessions, then require `server:view` at the explicit login boundary. Test authorized and cross-team callers. |

`server:open` and `server:view` represent the same authority. Remove `server:open` from the capability catalog, role fixtures, IAM dependencies, API checks, dashboard state, tests, and documentation. Use `server:view` for server and site login. Add a patch that replaces stored `server:open` grants with `server:view` and removes duplicates.

### Consolidate policy without removing enforcement

- Extend the existing capability decorator to resolve the team once and pass it to the handler. Test positional/keyword arguments, omitted teams, multiple teams, suspended teams, and operators. Preserve `functools.wraps` and Frappe signature handling.
- Use `iam.can`, `resolve_team`, and capability-scoped team queries consistently. Remove duplicate operator checks. Keep resource ownership explicit when the input is a server, snapshot, site, or notification ID.
- Guards do not replace query conditions or document permissions. Audit every team-scoped DocType for both hooks, an indexed team field, and denial when the team is absent. Reuse existing permission builders.
- Move membership and role reads behind IAM operations where they make authorization or recipient-selection decisions. Use `get_list` for customer reads. Keep justified system reads and writes explicit rather than replacing every `get_all` or bypass mechanically.
- Keep invitation, last-owner, and role-assignment rules in their controllers. Move Team deletion invariants and cleanup out of `api/teams.delete_team` into the existing controller lifecycle. Do the same for Team Role rules where API and Desk paths currently differ. Test effective Frappe access before changing permission helpers.
- Consolidate billing team resolution only at required shared entry points, updating callers together. Do not add compatibility aliases or rewrite all billing authorization for symmetry.
- Reproduce OTP expiry versus the email's stated expiry, duplicate development bypasses, resend throttling and attempt resets, GET-reachable mutations, and enrollment replay across rollback. Use standard Frappe controls. `setup_local` is currently not whitelisted; verify exposure before treating it as an HTTP defect.

**Gate:** IAM, guard, whitelist, team-scoped permission, preference, signup, site-login, and affected billing access tests pass. Test route and direct DocType access wherever both are exposed.

**Completed on 2026-09-23.** `server:view` now owns both visibility and login, the migration removes stored `server:open` grants, status polling cannot create a site session, resize uses `server:resize`, restart capability selection has one owner, and the unused billing team enumerator is gone. The shared guard resolves and passes one team. Team and Team Role deletion rules now run from controller lifecycles. User preferences enforce user and team ownership, while credential, service, and stored notification records have explicit operator-only hooks. Signup codes expire in 10 minutes, resend preserves failed attempts and is rate-limited, and a failed Pilot enrollment releases its replay claim. The local migration succeeded, the capability result was verified through `frappectl`, 162 focused backend tests passed, the patch registry passed, and the dashboard production build passed with the recorded baseline warnings.

## Phase 2: simplify server and site operations

### Give each decision one owner

```text
Route -> validated input + IAM -> operation owner -> Resource Action
                                                    |
                                          after_insert / after commit
                                                    v
                                       integration worker -> Atlas / Pilot
                                                    |
                                   verified receipt or scoped observation
                                                    v
                                   action outcome + owned local records

Billing owns eligibility, quotes, subscriptions, and repricing.
Virtual Machine owns Central identity and recorded observed state.
Site owns site identity and login/rename state, not another VM state.
```

- Simplify `submit_request` into a readable sequence: validate, authorize, deduplicate under the Team lock, resolve image and purchase, then insert intent. Keep one creation path with explicit inputs for trial, Pilot, Ubuntu, and restore. Preserve different readiness rules.
- Keep input rules in the typed boundary models and owning policy checks. Verify configured upper size limits, composition units, payload bounds, and SSH keys as well as positive values. Remove duplicate validation only when every caller still reaches the same rule.
- Put purchase operations behind billing catalog domain entry points. Provisioning currently imports dashboard billing routes and `_shared`; remove that reverse dependency without changing price or eligibility rules.
- Let Resource Action own status changes, pending-state definitions, timestamps, error clearing, and progress publication. Prefer one checked transition operation with explicit arguments over identical `mark_*` wrappers. Keep action-specific completion rules separate.
- Keep intake and remote dispatch separate because their transaction rules differ. Remove duplicate client construction and parsing where inputs are equivalent. Do not merge everything into one large file or add a dispatcher hierarchy.
- Put local VM construction with its controller and subscription creation with billing. The integration coordinates finalization from a verified receipt. Keep the VM, subscription, action links, and credential link atomic, with deterministic identities for retry.
- Stop double completion: `observe_server` advances actions, while `_finalize` and `process_command` advance stale copies again. Choose one observation-to-action path and lock/reload before transitions. Repeated and late callbacks must not regress completed actions.

### Preserve the difficult parts

| Invariant | Required implementation and test |
|---|---|
| One accepted create | Persist intent and dispatch marker before mutation; persist receipt before finalization. Recovery must not resend an uncertain create. |
| Correct budget reservation | Use the same Team lock and budget calculation for first submission and retry. `retry.revalidate_purchase` currently lacks the initial submission's Team lock. Test concurrent retries and submissions, including retained quotes. |
| Honest uncertainty | Timeout or failed lookup does not prove absence. Verify lookup pagination, ordering, and acceptance timing before permitting resend. Keep unresolved requests visible with bounded escalation. |
| Honest restart completion | Running alone is insufficient. `process_command` promotes an unconfirmed action to In Progress, which the next Running report can treat as a completed round trip. Test repeated Running and unrelated state changes. Require authoritative evidence or report an unconfirmed outcome. |
| Independent readiness | VM Running, Pilot availability, site readiness, rename acceptance, and rename completion are different facts. Do not collapse them into one success flag. |
| Recoverable external effects | Test crashes before dispatch, after remote acceptance, before receipt persistence, and during finalization. Keep accepted identity and credentials needed for recovery. |

Do not add a creation timeout that releases budget or permits resend while Atlas might still create the VM. Define what becomes overdue, what continues to reconcile, and what an operator can safely do. Remote failure, local finalization failure, and unknown outcome need different treatment.

### Complete lifecycle consolidation

- Queue trial creation after commit, removing inline `process_request` in `site_provisioning.create_trial_site` and the Site exception in `ResourceAction.after_insert`. Return the action identity immediately and let onboarding follow it. Preserve fast handoff, reload recovery, and duplicate-click behavior with a measured warm-image journey. This is an explicit proposed UX change.
- Make resize a durable Resource Action. Keep preset/composed pricing, disk-growth rules, and subscription changes in billing. The integration executes the remote operation; the action stores target and progress. Confirm target shape before repricing. Recover local billing failure without blindly repeating remote operations.
- Remove `resize_in_progress` only when all checks and UI readers use the action. Serialize resize with power and terminate. Preserve online disk growth, CPU/memory resize, idle-sleep policy, and current power-state behavior.
- Keep snapshot state on VM Snapshot. A terminate action waits for its final snapshot and must not destroy the VM if it fails. Reuse snapshot creation and recovery. Preserve restore restrictions and free-snapshot billing.
- Use lifecycle hooks and enqueue remote work after commit. Verify the actual write path: `save()` calls `on_update`; `db_set()` does not, although it calls `on_change`. Use an idempotent owner method or the correct hook rather than assuming a moved callback will run.

**Gate:** action, observation, provisioning-shape, resize, snapshot, Pilot credential, site, and affected billing creation/trial/resize tests pass. Include duplicate workers, callback races, revoked requester permissions, remote failure, and local recovery. No new remote contract is assumed.

**Completed on 2026-09-23.** Resource Action now queues every create, site, power, terminate, and resize operation after commit and owns state transitions, timestamps, customer-safe errors, current diagnostics, and Error Log links. Creation uses billing catalog entry points instead of dashboard routes. Virtual Machine owns mirror creation, and billing owns subscription creation and repricing. Trial creation returns its queued action. Resize stores one validated target, serializes against other actions, confirms the regional shape before repricing, and recovers a local billing failure without repeating a confirmed resize. The separate `resize_in_progress` state and the unused synchronous dashboard resize endpoint are removed. Restart waits for an observed state change before Running can complete it. The focused suites passed. The full app suite passed 1,646 tests with one skip. Migration, patch validation, live index verification through `frappectl`, and the dashboard production build also passed.

## Phase 3: finish domain ownership and failure handling

### Observation, services, and credentials

- Correct webhook ordering in `integrations/state_delivery._decide`: same-status reports are discarded before their timestamp is recorded. Test Running at T1, Running at T3, then delayed Stopped at T2. Advance the watermark under the existing record lock without repeating lifecycle effects.
- Consolidate state mapping and receipt validation where callback and detail-read contracts match. Validate payload types and timestamps. Keep sender authentication, identity, tenant checks, and source clocks explicit. Review delivery durability and reconciliation before adding a new receipt mechanism.
- Audit Site, Site Domain, VM admin hostname claiming, Region connections, and snapshot jobs. Persist accepted task identities where completion matters. Task acceptance is not rename or domain readiness. Keep retry and cleanup on the owning record.
- Review Team Service, Service Detail, add-on policy, storage provisioning, and Team partner/Connect calls. Consolidate equivalent provision/rotate/delete behavior; retain protocol-specific clients. Validate local plan and endpoint prerequisites before `BucketProvisioning.create_new` mutates remote storage. Preserve recovery after remote success and local failure.
- Review `sso.py` wrappers around shared minting. Delete wrappers that add no policy; preserve audience, scope, TTL, key selection, and verification distinctions. Do not expose arbitrary customer-controlled audiences or scopes through consolidation.
- Search actual credential callers before deletion or merging. Pilot Credential's comment says `mint` has no production caller, but server provisioning calls it. A comment is not deletion evidence. Do not merge credential DocTypes merely because both hold secrets.

### Errors that support recovery

- Keep the customer-safe Resource Action envelope and restricted diagnostics pattern for other resources. Persist actionable failures on the site, snapshot, or service that owns recovery. Link support detail through Error Logs. Do not store raw regional responses, bootstrap metadata, credentials, or tracebacks with local variables in customer-readable fields.
- Review broad catches at worker recovery, finalization, optional storage, hostname rename, and notification delivery. Keep them only where that boundary can record and recover the failure. Catch specific expected failures elsewhere.
- Preserve optional storage behavior initially, but make degraded setup visible and recoverable. Making storage mandatory changes the product contract and needs a decision.
- Use standard `frappe.log_error` with record references and safe detail. Frappe already supplies a traceback when no message is given; repeating that at every call is not simplification.

### Notifications with one event owner

- Define event types in fixtures; remove runtime registration after verifying callers and fixture coverage. Retain `provision_failure` if used for creation failure. Do not both delete and reuse it. Remove other types only after a reference search.
- Emit from the transition owner: creation failure, termination, snapshot failure, site readiness, and actions requiring attention. Queue after commit and deduplicate repeated transitions. Delivery failure must not roll back resource state and must remain retryable.
- Link to the right resource and translate messages. In the touched billing delivery path, correct the helper that swallows a send error before its caller records Sent. Distinguish queued email from successful delivery.
- Replace `mark_all_notifications_read`'s row loop and fixed 10000 cap with bounded bulk creation of missing Notification Read rows for visible notifications. Return the real unread count. This is not one update to Team Notification.
- Add database uniqueness for `(user, notification)` read markers and `(user, team, category)` preferences through `on_doctype_update`, after resolving existing duplicates. Test concurrent marking and preference writes.
- Reject unsupported categories instead of defaulting to Billing. Keep recipient selection behind IAM and user preferences separate from team membership.

**Gate:** ordering, malformed receipts, service recovery, token isolation, notification visibility, bulk/concurrent marking, duplicate events, and delivery failure tests pass. Desk shows safe errors, related records, and valid recovery actions.

**Completed on 2026-09-23.** Regional reports now advance their source watermark even when the state is unchanged, so a delayed older state cannot regress a server. Site rename, admin hostname, route, snapshot, and Resource Action failures keep a safe reason on the owning record and link full detail through Error Log. Resource lifecycle owners queue deduplicated notifications after commit. Event types come only from fixtures, all notification email uses the shared branded template, billing records queued delivery accurately, and read markers use bounded bulk inserts with database uniqueness. SSO and credential callers retain their distinct policy boundaries. Bucket, Cargo, and storage provisioning refactors are deferred by product direction. Migration, patch validation, pre-commit, the dashboard production build, and 1,659 tests passed with one skip. The repository-wide format check retains seven pre-existing findings outside this phase.

## Phase 4: consolidate the dashboard

Keep Vue 3, TypeScript, Frappe UI, Espresso, and the existing singleton composable pattern. Do not add Pinia or another request framework.

1. **Make checks meaningful.** Resolve phase-0 type findings without hiding application errors or silently upgrading Frappe UI. Enable explicit Biome rules and a lint script, then run both checks in CI. Keep automatic lint churn out of unrelated files.
2. **Simplify server workflows first.** Move fetching, filters, action execution, and site/bench opening out of `ServersPage` into domain composables. Reuse `useServers.runCommand`, `useBusyRunner`, and `submitOrThrow` before adding a mutation runner. Preserve synchronous popup creation for SSO.
3. **Give shared state one owner.** Feature components can read session, capabilities, and fleet state instead of passing the same flags through layers. Replace Owner/Admin name checks with server-provided capability or operation flags. Keep local dialog targets and interaction state local unless truly shared. Standardize empty/busy identity types; clear shared state on logout and team changes.
4. **Split at responsibilities.** Review the components below. Keep state with its owner instead of assigning a new file to every helper.

| Component | Responsibility to simplify |
|---|---|
| `ServersPage.vue` | Fleet selection, filters, actions, and dialog composition. |
| `ResizeServerDialog.vue` | Catalog/target selection, disk choice, price summary, submission. |
| `ServerMap.vue` | Viewport and interaction state versus node rendering, preserving animation. |
| `common/list-view/ListView.vue` | Table/query state and orchestration. Pagination and state components already exist. |
| `SpendingLimitsPage.vue` | Tier data and gates in a composable; tier presentation in billing components. |

5. **Remove page-level fetching and pass-through APIs.** Cover server, add-on, auth, onboarding, billing reports, invoices, and spending-limit pages, then cards such as PaymentMethodsCard. Use Frappe UI `useList` and `useDoc` for plain DocType reads after query and document permission tests pass, and delete routes that only forward those reads. Keep an API for composed domain data, policy beyond DocType access, cross-owner data, and operations. Keep domain rules with existing owners; pages compose the result.
6. **Consolidate request lifetimes.** Reuse confirmation/mutation patterns. Share stale-response handling only with explicit invalidation. Fix `useSnapshots.reload` and `useRegionalImages.reloadSnapshots` leaving loading set when scope clears mid-request. Test late success/failure, team switches, unmount, and timers.
7. **Preserve intentional reactivity.** Replace redundant derived-state watchers with computed values. `ServerMap`'s latched raster scale and `ConfigDesigner`'s model-output watcher are not automatic deletion candidates.
8. **Finish common/layout/domain tiers.** Reuse row actions, confirmations, empty/error states, and formatters. Move shell/navigation into the layout tier and loose billing components into their domain. Use named props interfaces, remove `any`, and use semantic Espresso classes where they cover the requirement.
9. **Consolidate formatting without changing meaning.** Use one date module and deduplicate number/spec/memory formatting. Preserve date-only billing values, site time zones, timestamp units, and display contexts. Different contexts can still need different formats.

Recheck earlier backlog items: billing-profile fetch duplication, `useBillingOverview` return shape, `useFleetRows`, gateway adapter discriminated union, VM/invoice enums, search-index loading, add-on exposure, team-settings/invitation navigation, duplicate Region types, and discarded reportview fetching. Mark resolved items as such. Implement remaining changes only with a demonstrated caller or user benefit. Align generated types with current schema rather than restoring obsolete fields or statuses.

**Gate:** type-check, lint, build, and focused UI tests pass. Exercise creation/reload recovery, restricted resize/power controls, team switching during requests, map interactions, lists, SSO, and failed submissions. Verify unchanged dates, amounts, and actions on touched billing screens. Changed screens handle loading, empty, error, disabled, and keyboard states.

## Phase 5: close the PR

- Complete the inventory with changes, deletions, retained owners, and explicit deferrals. No non-billing area disappears from scope because it is not a large file.
- Normalize region naming in affected internal interfaces and fields, including Resource Action's `atlas_instance` and VM's `cluster`, updating callers, hooks, fixtures, and types together. Limit billing edits to required references. Capability renames need matching fixtures and consumer coordination, or explicit deferral.
- Add only necessary data patches; no compatibility facades or deprecated aliases. Test populated data, partial application, and repeat execution. Put indexes and uniqueness in `on_doctype_update`.
- Finish affected Desk records: useful columns/filters, indexes, titles/search, read-only observed fields, safe diagnostics, links, and authorized recovery actions. A button needs a valid recovery operation behind it.
- Update module specs as each phase lands. At closure, fix relevant stale Asset/Atlas Instance language, capability claims, broken links, and contradictory delivery instructions. Avoid an unrelated documentation rewrite.
- Document changed API inputs, responses, capabilities, team ownership, errors, mutation methods, asynchronous status, and retry rules using the same typed models. Atlas's `api/routes/virtual_machines.py` shows shared operations with explicit arguments and typed contracts; adopt that clarity without copying its router.

### Final validation

Run focused suites during each phase. Before the single PR is ready, run the full Central suite, static checks, patch validation, dashboard checks, and build. Use Bench Python and Pilot as required by `CLAUDE.md`.

```bash
# From apps/central
../../env/bin/ruff check central
../../env/bin/ruff format --check central
python3 scripts/check_patches.py
pre-commit run --all-files

# From apps/central/dashboard; lint is added in this PR
yarn type-check
yarn lint

# From the bench root
pilot frappe --site central.localhost run-tests --app central
pilot build --apps central
```

Format changed files before the final check. Review tool-generated edits without overwriting pre-existing work. Verify patches on disposable populated data. Run real-region Pilot and Ubuntu creation/power/access, signup/site login, snapshot/restore, resize, and deletion checks from [local validation](LOCAL_ENVIRONMENT.md) where supported. Report unavailable infrastructure as a validation gap, never as a pass.

Review every changed line and the full diff. The PR description distinguishes preserved behavior, corrective fixes, and intentional UX changes such as queued trial creation. Report baseline failures and external dependencies precisely.

## Decisions and explicit deferrals

Approved defaults: one Central PR, no new remote contracts, queued trial creation, unchanged storage optionality with visible failures, unchanged billing policy, and API preparation without publication. `server:view` includes server and site login; `server:open` is removed. If signup latency requires synchronous dispatch, decide that before changing the Site exception.

- Defer merging Service API Key and Site Service Credential until current schema, callers, ownership, and rotation rules demonstrate a real simplification. Do not revive an obsolete schema proposal.
- Defer scoped grants, capability-version changes, and upstream restart-completion contracts. If the current contract cannot prove completion, show the limitation honestly and record the exact dependency.
- Defer unrelated billing defects and billing test repairs. Required access, lifecycle, and delivery corrections remain in scope as listed above.
- Record newly discovered structural or product decisions here before implementing them. Ordinary simplification within agreed behavior does not need a new design exercise.
