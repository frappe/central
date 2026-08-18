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

## PR 7 — frontend consolidation

One `RowActions` / `ConfirmDialog` / mutation-runner / empty-state / spec+memory formatter;
dedupe `get_billing_profile` (four concurrent fetchers) and reshape `useBillingOverview`'s
return; split `ServerMap.vue` (912 LOC) and extract `useFleetRows`; fix stale enums
(`Asset.status` missing `Resizing`, `InvoiceStatus`); make `gateway.ts` a discriminated union
on `adapter_key`; structure cleanup (`utils/`→`lib/`, flatten `composables/common/`, renames).
Plus the behavioural items: lazy-load the search index, feature-flag the addons page, wire
`/team/settings` + `/team/invitations` into the nav, drop the discarded `useServers`
reportview list.

## PR 8 — docs + tests

`CAPABILITIES.md` / `spec/IAM.md` / `spec/EXECUTION_PLAN.md` are materially wrong (capability
counts, retired `vm:*` vocabulary). Behavioural test gaps on the touched endpoints; fix
`test_atlas_register._wipe` (deletes every Atlas Instance and commits); freeze the `2099` /
`add_days` clocks; inject the `_verify_over_tunnel` retry delay; wire
`scripts/lib/central/test_wireguard.py` into CI; settle the doctype-dir-vs-`tests/` convention.

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
