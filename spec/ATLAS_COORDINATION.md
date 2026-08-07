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
