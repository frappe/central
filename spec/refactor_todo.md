# Central pre-1.0 refactor — remaining work

Companion to the delivered refactor PRs (guardrails → correctness → dead-code sweeps →
indexes → IAM hot-path cache → backend boundaries → notification engine). Tracks what is
left so it can be picked up cleanly. See also `spec/ATLAS_COORDINATION.md`.

## Large backend refactors (each its own PR)

- **Split `integrations/atlas.py`** (878 LOC) into `client` (outbound RPC) / `mirror` (event
  ingest + reconcile) / `tunnel` (WireGuard registration). Use a package facade
  (`integrations/atlas/__init__.py` re-exporting the public **and test-imported** names —
  `_on_vm`, `_on_vm_deleted`, `_remote_error_message`, etc. — so the ~16 call sites don't
  change). Collapse `AtlasClient`'s redundant construction paths (`for_region` is redundant —
  an Atlas Instance is `autoname:field:region`, so `name == region`) and its duplicate
  transports/auth-header copies. Correctness-sensitive (tunnel + event ingest) — test against
  the atlas suites.
- **Merge `Service API Key` + `Site Service Credential`** into one DocType with a
  `subject_type` discriminator — deletes a table, a controller, a TS type, and the dual loop
  in `services/llm.py`. **Needs a data migration.** If not worth it, record why.
- **Naming pass:** one noun for Asset/Server/VM, cluster vs region, `Order.desc` vs
  `frappe.qb.desc`; wrap the remaining bare `frappe.throw` strings in `_()`.

## PR 7 — frontend consolidation ✅ delivered

Shared `RowActionsMenu` (the seven row menus) + `ConfirmDialog` (the pending-target
confirms); deduped the four `get_billing_profile` fetchers onto the `useBillingOverview`
singleton; split `ServerMap.vue` into `MapHoverCard` and extracted `useFleetRows`; fixed the
stale enums (`InvoiceStatus` realigned to the DocType, `AssetStatus` `Resizing` made a
first-class member — `Asset.status` itself already matched the DocType); `gateway.ts` is a
discriminated union on `adapter_key`; `utils/`→`lib/`, flattened `composables/common/`; deduped
`formatMemory`; lazy-mounted the search index; feature-flagged the addons area (Central
Settings `enable_addons`); wired `/team/settings` + `/team/invitations` into the nav; dropped
the discarded `useServers` reportview list.

- **Not done — reshape `useBillingOverview`'s return** (it exposes raw `useCall` handles).
  Deferred: cosmetic, and reshaping churns all eight consumers for no behavioural gain. The
  dedupe (the substantive fix) landed; revisit only if a consumer needs the cleaner shape.
- The **naming pass** (Asset/Server/VM, `Region` TS collapse) stays in the backend-refactors
  section / deferred — untouched here.

## PR 8 — docs + tests

Done: `CAPABILITIES.md` / `spec/IAM.md` / `spec/EXECUTION_PLAN.md` corrected (15 caps incl.
`service:*`, role totals, retired `vm:*` → `server:*`); `test_atlas_register._wipe` scoped to
the regions each test creates (no longer deletes every Atlas Instance); `_verify_over_tunnel`
retry delay lifted to a patchable `VERIFY_RETRY_DELAY` (0 in the test setUp); wired
`scripts/lib/central/test_wireguard.py` into CI as a standalone job.

Remaining (each wants a throwaway-site test run to verify — the shared bench tracks
`develop`, and bench tests must not run against `central.localhost`):
- **Freeze the `add_days`/`nowdate` clocks** across the ~10 billing test files (needs a
  freezegun-style time fixture added first; applying it blind risks breaking those suites).
  The literal `2099` sentinel wasn't found — confirm it's gone or locate it.
- **Behavioural test gaps** on the touched endpoints (servers/teams/billing) — new tests.
- **Settle the doctype-dir-vs-`tests/` convention** (organizational; low value).

## PR 8b — CI hardening

Flip the deferred gates on once the cleanup above lands green: `vue-tsc --noEmit` (scope to
`src/`, exclude frappe-ui internals) and biome `preset: recommended`.

## Deferred / needs a decision

- **Rest of the schema pass:** composite indexes (`Asset(team, status)`, `Asset(cluster,
  status)`, `Team Invitation(email, status)`) via `on_doctype_update`; `Site.pilot_credential_id`
  Data→Link; regenerate drifted DocType type blocks; collapse the two `Region` TS types.
- **Scoped grants + `CAPABILITY_VERSION` bump** — needs bench-side coordination
  (`spec/ATLAS_COORDINATION.md`): land the bench reader together and keep `scope` defaulting to
  `"*"` so an un-updated bench keeps working.
- **Security PR (separate):** `create_server` size clamp, `create_site` billing gate,
  orphan-VM-on-throw, dev-mode OTP bypass, `resend_signup_code` rate limit, the GET-reachable
  mutations, `get_site` gating, `setup_local` role check, pilot-enroll replay — and the
  `User Notification Preference` cross-tenant read/write leak.
