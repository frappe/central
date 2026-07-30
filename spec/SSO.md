# SSO — Central-minted login

Central is the signing authority. It mints short-lived RS256 assertions; benches verify them
offline against Central's published JWKS. Atlas is not in the login path.

## Flows

**Bench (console) login** — `central.api.sso.get_bench_link`
1. Central mints `mint_bench_login(aud)` — `scope=bench`, 5 min, single jti.
2. Browser → `{gateway}/?sid=<jwt>`; the bench SPA exchanges it for a local session cookie.

**Site login** — `central.api.sites.get_site` → `_pilot_site_login_url`
1. Central resolves the site's hosting bench (audience + gateway) from `Site.pilot_credential_id`
   → `Pilot Credential` → `Asset.gateway_url`, then mints `mint_site_login(aud, site)` —
   `scope=site`, `site` claim, 5 min, single jti.
2. Browser → `{gateway}/api/v1/sites/<site>/login?sid=<jwt>`.
3. The bench verifies the assertion (JWKS, `aud`, `site`-match, single-use), logs into the
   Frappe site locally, and 302s to `.../desk?sid=<real session id>`.

If the pilot hasn't enrolled or its VM isn't Running, Central falls back to the Atlas-minted
`login_url` (`AtlasClient.regenerate_site_login`). Retiring that fallback + the deploy-time mint
is a follow-up once every bench is enrolled.

## Where tokens live

| What | Stored | Notes |
|------|--------|-------|
| Central signing key | `Central SSO Settings` — `private_key` (Password, encrypted), `public_key`, `kid` | Signs every assertion + bootstrap token |
| Bench durable credential | `Pilot Credential.token_hash` (SHA-256) | Plaintext bearer returned once at enroll, never stored |
| Site → bench binding | `Site.pilot_credential_id` | A reference, not a token |
| Bench/site login assertions | **nowhere** | Stateless JWTs — minted on demand, handed off, forgotten |
| Bootstrap single-use guard | Redis SETNX on the jti | Ephemeral |

On the bench (Pilot): the durable bearer is `bench.toml [central].auth_token` (Central holds only
its hash); `[admin].jwks_url`/`jwks_audience` are host-shared verification config (public); login
assertions are never stored — the single-use jti is tracked in-memory (`used_logins`) then dropped;
the real site session id lives in the Frappe site's own session store.

## Contract

- **RS256 + JWKS**, verified offline. Benches hold only the public key.
- **`aud` = the bench's `pilot_credential_id`**, assigned by Central. A SID for bench A is
  rejected by bench B; a pilot cannot self-declare its audience.
- **5-minute TTL + single-use jti.** Redeemable once, within five minutes; then dead.
- **Fail closed.** A bench rejects any assertion whose scope it does not understand
  (`Session.has_scope` is an allowlist) rather than downgrading to Administrator.
- **Extensibility (distinct scope).** Site login is Administrator today. A future constrained,
  per-user session must ride a NEW scope (e.g. `site_user`) so older benches reject it here — the
  identity is threaded through `SiteLogin.create_session(login_as=...)`, which defaults to
  Administrator. Adding it is additive: a new claim + a new scope handler, no contract change.
