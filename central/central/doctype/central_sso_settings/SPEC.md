# Central signing keys

## Purpose

Central SSO Settings owns the private keys used by Central. It holds two Ed25519 keys, one for each plane that verifies Central tokens:

| Key | Signs | Published at |
|---|---|---|
| Atlas | Atlas admin, proxy, Cargo, and Datum tokens | `<central-url>/api/method/central.api.jwks.get_atlas_jwks` |
| Pilot | Bench login, site login, and Pilot enrollment tokens | `<central-url>/api/method/central.api.jwks.get_jwks` |

The keys are separate so that a key that leaks compromises one plane only. Both use the `EdDSA` algorithm and a key identifier in the `central:` namespace.

## Configuration

A System Manager opens Central SSO Settings and selects **Initialize Atlas Signing Key** and **Initialize Pilot Signing Key**. Each button shows only while its key does not exist. Each action calls `initialize_signing_key(plane)` with `atlas` or `pilot`. It creates one encrypted private key, one public key, and an identifier. Repeated or concurrent requests keep the same key. An incomplete saved configuration blocks initialization rather than replacing a key that a verifier may already trust.

Configure Atlas `central_jwks_url` with the Atlas endpoint. Initialize the Atlas key before Atlas fetches this URL. Atlas rejects an empty trust set.

Central gives each Pilot the Pilot endpoint at enrollment and seeds the Pilot key set into a new server. Initialize the Pilot key before you create a server.

Both endpoints return raw JWKS documents. They return an empty key set before initialization. Neither endpoint generates keys or exposes private key material. No automatic key initialization runs on migration. Operators must initialize both keys explicitly on each Central deployment.

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

`central.tests.test_sso_keys` checks the Pilot key: initialization permissions, an unknown plane, repeated initialization, partial configuration, public-only discovery, separate Atlas and Pilot key sets, token verification, and a forged token. `central.tests.test_atlas_sso` checks the same rules for the Atlas key, plus token claims and invalid region IDs.

`central.tests.test_atlas_sso` can also run the actual local Atlas and Pilot verifier implementations. Atlas must be installed in the validation bench. Add the pinned Pilot checkout to `PYTHONPATH` to include its verifier. The tests reject a token for another region or Pilot audience. Missing consumer checkouts cause those tests to skip, so a passing suite alone does not prove consumer validation ran.
