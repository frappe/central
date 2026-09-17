# Central signing keys

## Purpose

Central SSO Settings owns the private keys used by Central. Pilot and the existing service consumers use RSA. Regional Atlas requests use a separate Ed25519 key because Atlas accepts only Ed25519 keys in its Central trust set.

## Configuration

A System Manager opens Central SSO Settings and selects **Initialize Atlas Signing Key**. The action creates one encrypted private key, one public key, and an identifier in the `central:` namespace. Repeated or concurrent requests keep the same key. An incomplete saved configuration blocks initialization rather than replacing a key that Atlas may already trust.

Configure Atlas `central_jwks_url` with `<central-url>/api/method/central.api.jwks.get_atlas_jwks`. Initialize the key before Atlas fetches this URL. The endpoint returns an empty key set before initialization. Atlas rejects an empty trust set.

Pilot continues to use `<central-url>/api/method/central.api.jwks.get_jwks`. Both endpoints return raw JWKS documents. Neither endpoint generates keys or exposes private key material.

The new fields are optional. Schema synchronization adds them without changing existing RSA data. The post-sync patch `rename_sso_rsa_fields` preserves the existing RSA key identifier, public key, and encrypted private key under `rsa_key_id`, `rsa_public_key`, and `rsa_private_key`. It stops if both field sets contain data. No automatic key initialization runs on migration. Operators must initialize the Atlas key explicitly on each Central deployment.

## Operation

`central.sso.mint_atlas_token(region_id)` creates a five-minute internal credential. Its issuer and subject are `central`. Its audience is `atlas-admin:<region_id>`. Its scope and tenant claims are `*`, as required for Central regional authority.

`central.sso.mint_proxy_token(region_id)` uses the same key for a regional proxy. Its audience is `atlas-proxy:<region_id>` and its scope is `site:* domain:*`. It has no tenant claim, because the proxy refuses a token with one. [Site Domain](../site_domain/SPEC.md) uses it.

These functions are not a public API. An integration caller must authorize the requested operation through Central IAM and select the correct tenant before it sends a regional request. This stage supplies token signing; connecting the regional client follows in stage 0C.

The initializer locks the DocType metadata row because a Single DocType has no parent document row. It then reloads the saved settings with a locking read. This prevents two initializers from publishing different keys. Initialization records an operator comment on the settings document.

A missing key blocks token minting with an operator instruction. Key rotation and automatic recovery of damaged signing material are not implemented. Restore the saved configuration if it becomes incomplete.

## Validation

`central.tests.test_atlas_sso` checks initialization permissions, repeated initialization, partial configuration, public-only discovery, token claims, invalid region IDs, and separate RSA and Ed25519 trust sets.

The same module can run the actual local Atlas and Pilot verifier implementations. Atlas must be installed in the validation bench. Add the pinned Pilot checkout to `PYTHONPATH` to include its verifier. The tests reject a token for another region or Pilot audience. Missing consumer checkouts cause those tests to skip, so a passing suite alone does not prove consumer validation ran.

The local validation used both consumer implementations and concurrent operator HTTP initialization. Regional HTTP access and a real Pilot login remain stage 0C and staging acceptance checks.
