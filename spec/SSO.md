# SSO: Central-minted login

Central is the signing authority. It mints short-lived EdDSA login assertions with its Pilot key. A bench verifies them offline against the JWKS that Central publishes. Atlas is not in the login path.

## Regional authentication

Atlas regional requests use a separate Ed25519 key and public endpoint. Pilot login and enrollment use the Pilot Ed25519 key. Read [Signing keys](../central/central/doctype/central_sso_settings/SPEC.md) for initialization, token authority, and verifier checks.

## How does a member log in?

**Bench (console) login**: `central.api.sso.get_bench_link`

1. Central resolves the server's `gateway_url` and the `audience_id` of its Active `Pilot Credential`.
2. Central mints `mint_bench_login(audience)`: `scope=bench`, 60 minutes, single-use `jti`.
3. The browser opens `{gateway}/?sid=<jwt>`. The bench SPA exchanges it for a local session cookie.

**Site login**: `central.api.sites.login_site`

1. `login_site` checks `server:view` and calls `Site.get_login_url`.
2. `Site.get_pilot_access` reads `Virtual Machine.gateway_url` and the `audience_id` of the Active `Pilot Credential` for the site's `{server, team}`.
3. `central.integrations.pilot.fetch_site_login_url` mints `mint_site_login(audience, site)` (`scope=site`, `site` claim, 5 minutes) and POSTs it to `{gateway}/api/v1/sites/<site>/login` as the `Bearer`.
4. The bench verifies the assertion (JWKS, `aud`, `site` match), logs into the Frappe site locally, and returns `{url: .../desk?sid=<session id>}`.
5. `on_host` moves that URL onto the site's public host. Central redirects the member there.

If the Pilot has not enrolled, the server has no Active Pilot Credential and there is no login URL.

The console (bench) login is carried by the browser. Only the site login is a relay from Central to the bench.

## Where do tokens live?

| What | Stored | Notes |
|------|--------|-------|
| Pilot signing key | `Central SSO Settings`: `pilot_private_key` (Password, encrypted), `pilot_public_key`, `pilot_key_id` | Signs bench login, site login, and bootstrap tokens. An operator initializes it. |
| Bench durable credential | `Pilot Credential.token_hash` (SHA-256) | Plaintext bearer returned once at enroll, never stored |
| Site to bench binding | `Site.server` to `Pilot Credential` (`server`, `audience_id`) | A reference, not a token |
| Bench and site login assertions | Nowhere | Stateless JWTs, minted on demand and handed off |
| Bootstrap single-use guard | Redis SETNX on the `jti` | Ephemeral |

On the bench (Pilot), the durable bearer is `bench.toml [central].auth_token`. Central holds only its hash. `[admin].jwks_url` and `jwks_audience` are public verification configuration shared by the host. The bench does not store login assertions. It tracks the single-use `jti` in memory (`used_logins`) and then drops it. The real site session id lives in the Frappe site's own session store.

## Contract

- **EdDSA (Ed25519) and JWKS**, verified offline. Benches hold only the public key.
- **`aud` is the bench's `audience_id`**, assigned by Central. Bench B rejects a SID for bench A. A Pilot cannot declare its own audience.
- **Short TTL.** The bench login SID lasts 60 minutes, is carried by the browser, and is single-use (the bench tracks the `jti`). The site assertion lasts 5 minutes and goes only from Central to the bench. The browser never sees it.
- **Fail closed.** A bench rejects any assertion whose scope it does not understand (`Session.has_scope` is an allowlist). It does not downgrade to Administrator.
- **Extensibility (distinct scope).** Site login is Administrator today. A future per-user session must use a new scope (for example `site_user`), so that older benches reject it. The identity goes through `SiteLogin.create_session(login_as=...)`, which defaults to Administrator. Adding it is additive: a new claim and a new scope handler, with no contract change.

## Which tokens does Central mint?

Central separates token purposes by the required `scope` claim and by the audience. Login and enrollment tokens use the Pilot key. Regional tokens use the Atlas key. Both keys are Ed25519.

| scope | minter | `aud` | TTL | Key | Consumed by |
| --- | --- | --- | --- | --- | --- |
| `bench` | `mint_bench_login` | bench's `audience_id` | 60 min | Pilot (Ed25519) | the bench (login SID) |
| `site` | `mint_site_login` | bench's `audience_id` | 5 min | Pilot (Ed25519) | the bench (site login) |
| `enroll` | `mint_bootstrap_token` | `pilot_credential_id` | 30 min | Pilot (Ed25519) | Central (`verify_bootstrap_token`, asserts `scope == enroll`) |
| `datum` | `mint_datum_token` | `atlas-datum:<region id>` | 7 days | Atlas (Ed25519) | Datum, for metrics and logs |
| regional | `mint_atlas_token` / `mint_proxy_token` / `mint_cargo_token` | `atlas-admin:<region id>` / `atlas-proxy:<region id>` / `atlas-cargo:<region id>` | 5 min | Atlas (Ed25519) | Atlas, the regional proxy, Cargo |

One `datum` token serves both write paths. One route hands it out: `central.api.pilot.datum_token`. Datum tells metrics from logs by the route the Pilot posts to, not by the credential. A second token would carry the same `resource_id` and the same authority. It is signed with the Atlas key, not the Pilot key, because Datum verifies against the merged key set that Atlas publishes. `iss` is the literal `central`, and the key id has the `central:` namespace. Datum uses these two values to bind one to the other. The audience names one region, so every other region refuses the token.

The token carries `resource_id` and `access: ["write"]` as top-level claims, which `Identity.from_claims` reads directly. Datum stamps every row with `resource_id`, so a Pilot cannot write as another resource. Datum serves no reads.

There is no revocation list. The 7-day TTL and the Pilot's re-fetch on 401 or near expiry (`api/pilot.py`) are the bound. `verify_bootstrap_token` requires `scope`, so Central never accepts a `bench` token as an enrollment token. Central refuses a `datum` token earlier, on its signature.

`mint_datum_token` needs the Atlas signing key, so an operator must initialize it in Central SSO Settings before any Pilot can send telemetry. The Pilot tokens need the Pilot signing key in the same way. A server creation fails before dispatch without it.
