# Central v0.2 delivery

## Purpose

Deliver the [rewrite contract](REWRITE_SCOPE.md) through reviewed phase PRs. The integration branch is `v0.2` in `frappe/central`.

## Branch workflow

```text
frappe/central develop
    |
    +-- v0.2
          ^
          +-- feature/v0.2-plan                 documentation review
          +-- feature/v0.2-phase-0-foundation  PR after plan approval
          +-- feature/v0.2-phase-1-contracts   PR after phase 0
          +-- feature/v0.2-phase-2-signup      PR after phase 1
          +-- remaining phase branches

user merges accepted v0.2 -> develop
```

Create `v0.2` from the main repository's `develop`, not the superseded rewrite branch. The initial base is `c2565d80`.

Create each phase branch from the latest accepted `v0.2`. Use `v0.2` as the PR base. Do not build a stack of unreviewed phase branches.

If a phase needs several PRs, number them within that phase. Merge and validate each accepted PR before the dependent PR starts.

Review and merge approval are separate from implementation authorization. Do not merge a phase without review. The user performs the final merge into `develop`.

Close superseded PR #321 without deleting its branch. Preserve the unfinished local changes. Use the old work as a reference, not as an automatic cherry-pick list.

## Reuse from the old branch

| Candidate | Required review before reuse |
|---|---|
| Tenant ID allocation | Existing-data mapping, sequence safety, immutability, uniqueness, and migration order. |
| Ed25519 signing | Consumer compatibility, first-use concurrency, operator permission, publication delay, and key retirement. |
| Region fields | Required data transfer, remote identity validation, endpoint validation, and minimal target fields. |
| Token tests | Verify against actual consumer code, not only Central's own decoder. |
| Webhook deletion | Replace credential binding, revocation, operation completion, and failure reporting first. |
| Billing Link changes | Prove target records exist and preserve stored subscription identities. |

Do not copy the removal of the patch guard as part of this rewrite. A change to validation tooling needs its own concrete reason.

## Phase 0: identity, region, and signing foundation

**Result:** Central has verified Team and Region identities and can authenticate to the selected regional APIs.

Inventory staging data and token consumers. Add tenant IDs with the backfill and constraints. Define Region endpoints and migrate required Atlas Instance data. Implement and test signing-key lifecycle.

Update the related Desk forms, permissions, tests, and current specifications. Remove obsolete data only after its references are handled.

Keep the phase small through three review units if needed: Team identity, signing, then Region migration. All PRs target `v0.2`.

Acceptance:

- A populated migration preserves Team ownership and required Region data. Repeating it is safe.
- Concurrent Team creation cannot allocate the same committed tenant ID.
- Tenant ID changes and tenant `0` are denied for customer Teams.
- Atlas accepts Central keys and tokens. Missing headers and cross-Team resource reads are denied.
- Proxy tokens have the correct audience and cannot reuse an Atlas tenant token.
- All existing token consumers pass the agreed cutover checks.
- Key administration denies non-operators. First use and rotation have concurrency tests.

## Phase 1: API contracts and regional reads

**Result:** Central uses typed, versioned contracts for new regional reads and serves a documented customer read API.

Wrap the generated Atlas client under `central/integrations/`. Pin its source artifact or revision. Add timeouts, safe error mapping, tenant headers, and pagination.

Resolve image snapshot fields and release metadata with Atlas and Cargo. Build the image catalog from that contract.

Introduce the minimal typed Central API core and generated TypeScript client. Wire Region and image selection into the dashboard. Define session authentication and CSRF handling.

Acceptance:

- Contract tests validate requests and responses against the selected OpenAPI revision.
- A tenant with more than one page of resources returns a complete result.
- Region failures appear as stale or unavailable data, not an empty healthy fleet.
- Image selection rejects unavailable, incompatible, or incomplete images.
- Real Atlas and proxy authentication tests pass.
- API and client generation has a deterministic drift check.

## Phase 2: one complete trial signup

**Result:** A customer creates a trial and enters its site through the Central dashboard.

Introduce the target Server and Site records, stable resource references, durable signup request, and Pilot credential delivery. Migrate the Asset name and links in this phase.

Implement automatic names, prepared-image signup, bounded readiness, site discovery, and login. Include the minimum observation loop and recovery needed by signup.

Preserve the existing billing eligibility rules. Make only required billing reference changes. Replace enrolment when metadata delivery and recovery are ready.

Acceptance:

- One customer Team receives one trial VM and one existing image site for one accepted signup request.
- Repeated customer submissions do not create duplicate requests or VMs.
- An uncertain create cannot trigger an automatic second VM.
- Worker restarts and failures between remote acceptance and local persistence have a tested recovery path.
- A credential is bound to the right Server. Another Team cannot use the resulting login or read the request.
- Warm and cold startup work. The UI reports progress and a bounded failure or unknown outcome.
- A real region proves metadata bootstrap, automatic routing, and site login.
- Required billing links and migration counts remain valid.

## Phase 3: lifecycle, reconciliation, and sleep

**Result:** Server operations settle correctly and remain recoverable through outages and sleep cycles.

Extend the shared observation path for power, deletion, snapshots, console, and supported resize operations. Add fleet reconciliation, source freshness, work recovery, and operator actions.

Coordinate any missing migration or operation-completion contract with Atlas. Do not infer restart completion from the running state alone.

Move all required webhook effects into the observation path. Remove the webhook, old Atlas client, tunnel registration, and obsolete host scripts after the replacement works.

Retire Atlas Instance after its remaining callers and data references are handled. Do not copy its tunnel credentials into Region during phase 0.

Acceptance:

- Incomplete pagination, delayed reads, wrong-tenant `404`, timeouts, and server errors cannot falsely terminate a resource.
- Concurrent fleet and focused reads cannot replace a newer observation with an older one.
- Confirmed deletion revokes credentials and applies required subscription effects once.
- Actions survive worker restart, settle by their actual effect, and expose an unknown remote outcome when necessary.
- A sleeping VM remains asleep during fleet synchronization and wakes after customer traffic.
- Failed wake and stopped-for-maintenance states are not reported as healthy sleep.
- Resize and migration behavior matches the selected Atlas release. Conflicting controls are disabled or rejected clearly.

## Phase 4: site operations and domains

**Result:** Customers manage supported sites and names through Central with reliable routing and certificate state.

Add friendly regional names and customer domains. Integrate Pilot tasks for rename and supported site operations. Specify the certificate contract before implementing either side.

Support additional same-Team sites for the server product only when that product requires them. Do not reintroduce pooled trials.

Acceptance:

- Automatic, friendly regional, and customer-domain routes use the correct proxy path.
- Domain ownership and cross-Team uniqueness are enforced.
- Route success with certificate failure remains recoverable and never reports active.
- Rename keeps the Central Site identity and the agreed old-hostname behavior.
- Cleanup and retries are safe after either system restarts.
- Dashboard and Desk show DNS, route, certificate, and task failures where users act.

## Phase 5: services and remaining non-billing modules

**Result:** The wider non-billing code follows the same ownership, permission, and error rules.

Use separate review units for services and Cargo, telemetry, IAM and partners, notifications, and shared dashboard components. Audit each area in the scope table.

Confirm Cargo bootstrap configuration. Verify Datum labels, token refresh, and credential revocation. Keep monitoring compatible with the sleep policy.

Acceptance:

- Every area has a recorded review result and focused tests for changed behavior.
- Each changed Team-scoped DocType has list and document permission tests, including cross-Team denial.
- Thin routes, domain-owned behavior, and integration-only remote calls follow `CLAUDE.md`.
- Notification and telemetry failures leave useful operator state.
- Passport and Connect ownership and credentials remain valid.
- Dashboard components use the pinned Frappe UI version and pass state and accessibility checks.

## Phase 6: staging acceptance

**Result:** The accepted `v0.2` branch is ready for the user's merge into `develop`.

Run the complete app suite, required checks, dashboard build, populated migration rehearsal, and real-region scenarios. Run the full billing suite for integration changes.

Test upgrade from staging's actual schema, including any partially applied earlier rewrite. Record unresolved operational risks and rollback steps.

Acceptance:

- Trial signup, login, idle sleep, wake, upgrade, deletion, and domain flows pass on the selected region release.
- Central and remote restarts do not lose pending operations or create duplicate resources.
- Customer permissions and operator recovery work through the supported interfaces.
- No scheduled task, import, route, generated client, or document refers to removed behavior.
- The migration report reconciles required records, references, credentials, and remote resource identities.
- The user reviews the release evidence before merging to `develop`.

## Rules for every PR

1. State the problem, final behavior, scope, and dependency revisions.
2. Include schema patches with the code that needs them.
3. Include focused behavior, denial, and failure tests.
4. Deliver the matching dashboard and Desk controls when the behavior is user-facing.
5. Update the authoritative module documentation in the same PR.
6. Review every changed line before committing.
7. Record checks, failures, and untested dependencies accurately.
8. Obtain review before merging into `v0.2`.

Use the repository's Conventional Commit format. Do not add co-author or agent metadata.

Run the commands in `CLAUDE.md` from a correctly configured bench. Run the full suite before a broad refactor. Do not mass-format unrelated files to hide baseline failures.

Documentation-only PRs need link, content, conflict-marker, and diff checks. They do not require a database migration or application build.
