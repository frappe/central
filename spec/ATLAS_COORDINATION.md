# Atlas / bench coordination

Central-side changes in the pre-1.0 refactor that touch a contract shared with
Atlas or a deployed bench (pilot). The goal is to keep the Atlas-side footprint
**small** — most token/permission work below is Central-only and needs no Atlas
change. Only the first item requires a coordinated bench-side change.

## Requires a coordinated Atlas / bench change

### 1. Scoped grants in the `fc_teams` OIDC claim (+ `CAPABILITY_VERSION` bump)
- **Central change (deferred, not yet landed):** wire `Team Member.resource_type` /
  `resource_name` through `resolve_user_grants` / `can`, and emit the real per-grant
  `scope` in the `fc_teams` claim instead of the hardcoded `"*"`. Bump
  `CAPABILITY_VERSION` (`central/iam.py`).
- **Why Atlas is affected:** the bench mirrors the `fc_teams` claim from the OIDC
  userinfo response (`central/oauth.py`) into its own `BENCH_CAPS`. Today every grant
  carries `scope: "*"`; after the change a grant may be scoped to a single server
  (`{resource_type: "Server", resource_name: <id>}`). A bench that assumes `"*"` would
  either ignore scope (over-permit) or misread the claim.
- **Bench-side work required:** read `scope` per grant and enforce it (fall back to
  `"*"` when absent, so the change is backward-compatible during rollout). Honor the
  bumped `cap_version` for drift detection per `CAPABILITIES.md`.
- **Rollout:** bump `CAPABILITY_VERSION` and ship the bench reader together; keep the
  claim additive (scope defaults to `"*"`) so an un-updated bench keeps working.

### 2. HMAC-signed `event` webhooks (replaces token auth for that one endpoint)
- **Central change:** `central.api.atlas.event` moves to `allow_guest=True` and is
  gated by the `@verify_atlas_webhook` decorator (ordered under `@frappe.whitelist`,
  matching `central/utils/guards.py`) — an HMAC-SHA256 over
  `X-Atlas-Timestamp + raw body`, keyed on a new `Atlas Instance.webhook_secret`
  (minted/rotated alongside the service-user creds; see `TUNNEL.md`'s "Per-Atlas
  Central service user"). The gate stashes the verified context (cluster, raw body,
  signature, timestamp) on `frappe.local.atlas_webhook`; `ingest_event` no longer
  resolves the sender from `frappe.session.user` (`_atlas_cluster()` is deleted) and
  persists the raw bytes + signature so the stored `Atlas Event` row stays
  re-verifiable. `ping`/`sizes`/`images` are unaffected, still plain token auth.
- **Why Atlas is affected:** Atlas must sign `post_event` requests
  (`X-Atlas-Region`/`X-Atlas-Timestamp`/`X-Atlas-Signature` headers,
  `hmac.compare_digest`-verified) and must send **no**
  `Authorization` header on them — Frappe authenticates any token it is given even
  on an `allow_guest` route, so including one would let a stale `api_secret` 401 a
  correctly signed event. An unsigned `event` call is rejected outright once
  Central's gate is live.
- **Atlas-side work required:** `CentralClient.post_event` signs the exact bytes
  sent (`data=`, not `json=` — `requests`'s own serialization isn't guaranteed
  byte-identical to what's signed); `Central Settings` gains a `webhook_secret`
  field; `deliver()`'s "not registered" skip gate is extended to also require
  `webhook_secret`, so a build with the signing code but no secret yet just skips
  (durable outbox) instead of sending unsigned.
- **Rollout (hard cutover, no contract-version field — uses doctype state as the
  readiness signal instead):** (1) ship Central's schema + mint/push, endpoint
  unchanged — dormant; (2) ship Atlas's schema + signing + the extended skip gate;
  (3) re-register every `Atlas Instance` to push fresh `webhook_secret`, confirm
  `status="Active"` instances all have one set; (4) only then deploy Central's
  gate flip (`allow_guest=True` + signature-only). Flipping (4) before (3) is
  complete for a region's instance permanently breaks that region's event delivery
  until it's re-registered.

## Central-only — token-adjacent, but **no** Atlas/bench change needed

- **Shorten the Datum `METRICS_TTL`** (1 year → days/week): the pilot already
  re-fetches the metrics token on 401 and near expiry (`central/api/pilot.py`), so a
  shorter TTL is transparent to the bench.
- **`jti` / credential binding for metrics-token revocation:** Central mints and
  Central's `Pilot Credential` revocation invalidates; the bench only presents the
  token and re-fetches on 401. No bench change.
- **Assert `scope` as a required claim in `_mint`/verify** (`central/sso.py`): the
  tokens already carry `scope`; the verifiers are Central-side. Internal hardening.
- **Restrict `report_pilot_event` to a Server-category allow-list:** a well-behaved
  pilot only dispatches Server events already; Central just refuses out-of-scope ones.
  No change unless a bench was sending billing events (it should not).

## Deliberately unchanged (so Atlas stays untouched)

- The inbound Atlas HTTP endpoints `central/api/atlas.py` `register`/`sizes`/`images`/
  `ping` — kept as-is (annotated).
- The Atlas **event payload shape** consumed by the mirror (`mirror_vm`/`mirror_site`
  via `central/mirror.py`) — the PR-6 mirror dedup did not change the wire contract.
- `Asset` / `Site` mirrored field set — no fields the bench reports were removed.
