# Central signing keys

## Purpose

Central SSO Settings owns the private keys used by Central. It holds one key for each plane that verifies Central tokens:

| Key | Algorithm | Signs | Published at |
|---|---|---|---|
| Atlas | `EdDSA` | Atlas admin, proxy, Cargo, and Datum tokens | `<central-url>/api/method/central.api.jwks.get_jwks` |
| Pilot | `EdDSA` | Bench login, site login, and Pilot enrollment tokens | `<central-url>/api/method/central.api.jwks.get_jwks` |
| OIDC | `RS256` | OpenID Connect ID tokens, such as Warpgate sign-in | `<central-url>/api/method/central.api.oidc.get_jwks` |

Central uses a separate signing key for each plane. The shared endpoint publishes the Atlas and Pilot public keys, so consumers must also enforce issuer, audience, and token purpose. The OIDC key has its own endpoint, because OpenID Connect clients accept only RS256 keys. Every key identifier is in the `central:` namespace.

## Configuration

A System Manager opens Central SSO Settings and selects **Initialize Atlas Signing Key**, **Initialize Pilot Signing Key**, and **Initialize OIDC Signing Key**. Each button shows only while its key does not exist. Each action calls `initialize_signing_key(plane)` with `atlas`, `pilot`, or `oidc`. It creates one encrypted private key, one public key, and an identifier. Repeated or concurrent requests keep the same key. An incomplete saved configuration blocks initialization rather than replacing a key that a verifier may already trust.

Configure Atlas `central_jwks_url` with the shared `central.api.jwks.get_jwks` endpoint. Initialize the Atlas key before Atlas fetches this URL. Atlas rejects an empty trust set.

Central gives each Pilot the shared endpoint at enrollment and seeds the shared key set into a new server. Initialize the Pilot key before you create a server.

The endpoint returns a raw JWKS document. `get_jwks` publishes both initialized Pilot and Atlas public keys. An uninitialized plane contributes no key. An incomplete saved key blocks publication. The endpoint does not generate keys or expose private key material. No automatic key initialization runs on migration. Operators must initialize both keys explicitly on each Central deployment.

## Operation

`CentralSSOSettings.get_signing_key(plane)` returns the private key and its identifier. `get_public_key(plane)` returns the public key that verifies the plane's tokens. Both block with an operator instruction when the key does not exist.

`central.sso.mint_atlas_token(region_id)` creates a five-minute internal credential with the Atlas key. Its issuer and subject are `central`. Its audience is `atlas-admin:<region_id>`. Its scope and tenant claims are `*`, as required for Central regional authority.

`central.sso.mint_proxy_token(region_id)` uses the Atlas key for a regional proxy. Its audience is `atlas-proxy:<region_id>` and its scope is `site:* domain:*`. It has no tenant claim, because the proxy refuses a token with one. [Site Domain](../../../infrastructure/doctype/site_domain/SPEC.md) uses it.

`central.sso.mint_cargo_token(region_id)` uses the Atlas key for the regional Cargo host. Its audience is `atlas-cargo:<region_id>` and its scope is `bucket:*`.

`central.sso.mint_datum_token(region_id, resource_id)` uses the Atlas key for the credential that a Pilot presents to the Datum of its region. Its audience is `atlas-datum:<region_id>` and its scope is `datum`. It carries the `resource_id` claim and the `access` claim `["write"]`. It is valid for 7 days. A blank `resource_id` blocks minting.

`mint_bench_login`, `mint_site_login`, and `mint_bootstrap_token` use the Pilot key. Read [SSO](../../../../spec/SSO.md) for their claims.

`central.integrations.atlas.AtlasClient` signs every regional request with the Atlas key. These functions are not a public API. A caller must authorize the requested operation through Central IAM and select the correct tenant before it sends a regional request.

The initializer locks the DocType metadata row because a Single DocType has no parent document row. It then reloads the saved settings with a locking read. This prevents two initializers from publishing different keys. Initialization records an operator comment on the settings document.

Key rotation and automatic recovery of damaged signing material are not implemented. Restore the saved configuration if it becomes incomplete.

## Validation

`central.tests.test_oidc` checks the OIDC key and the provider: ID token signature, issuer and key ID, the uninitialized key, client secret checks, and the discovery path. `central.tests.test_sso_keys` checks the Pilot key: initialization permissions, an unknown plane, repeated initialization, partial configuration, public-only discovery, combined public discovery, token verification, and a forged token. `central.tests.test_atlas_sso` checks the same rules for the Atlas key, plus token claims and invalid region IDs.

`central.tests.test_atlas_sso` can also run the actual local Atlas and Pilot verifier implementations. Atlas must be installed in the validation bench. Add the pinned Pilot checkout to `PYTHONPATH` to include its verifier. The tests reject a token for another region or Pilot audience. Missing consumer checkouts cause those tests to skip, so a passing suite alone does not prove consumer validation ran.
