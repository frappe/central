# Central Spec

## What does v0.2 cover?

v0.2 covers trial signup, Pilot server creation and access, plain Ubuntu creation, server power actions, resize, snapshots, and the web console. Central routes custom domains through Site Domain, registers each region's Cargo, and asks Pilot to rename the trial site and the admin domain. The regional proxy terminates TLS for a regional name. Pilot holds the certificate for a custom domain.

- [Integrations](INTEGRATIONS.md): ownership and the contracts with Atlas, Pilot, and Cargo.
- [Staging validation](STAGING_VALIDATION.md): contract tests, region connection, and staging evidence.

Open work is tracked in [GitHub issues](https://github.com/frappe/central/issues).

Each module specification below describes current behavior. Update it in the same change as the behavior.

## Module specifications

- [Team network identity](../central/identity/doctype/team/SPEC.md): allocation, immutability, and migration of tenant IDs.
- [Signing keys](../central/central/doctype/central_sso_settings/SPEC.md): separate Atlas, Pilot, and OIDC trust, operator initialization, and token verification.
- [Regional configuration](../central/infrastructure/doctype/region/SPEC.md): signed connection checks, tenant selection, and regional identity.
- [Image offerings](../central/infrastructure/doctype/image_offering/SPEC.md): presentation records and on-demand regional System image discovery.
- [Resource actions](../central/infrastructure/doctype/resource_action/SPEC.md): durable intent, states, authorization, and recovery for server operations.
- [Team SSH keys](../central/infrastructure/doctype/team_ssh_key/SPEC.md): public login keys, server selection, and rotation.
- [Proxy routes](../central/infrastructure/doctype/site_domain/SPEC.md): site and custom-domain routes on the regional proxy, with retry and delete.
- [Trial sites](../central/infrastructure/doctype/site/SPEC.md): the site a Pilot image carries, its predictable address, and the signup handoff.
- [Products](../central/signups/doctype/product/SPEC.md): apps customers sign up for from their own page, and the image their trial starts.
- [VM snapshots](../central/infrastructure/doctype/vm_snapshot/SPEC.md): the free-snapshot pricing rule, daily snapshots, terminate with a snapshot, and restore.

## Cross-cutting specifications

- [IAM](IAM.md): Central identity and permission model.
- [Capabilities](../CAPABILITIES.md): the capability vocabulary and fixtures contract.
- [SSO](SSO.md): login flows, token types, and consumer contracts.
- [Inbound webhooks](WEBHOOKS.md): the contract a region signs and sends its reports with. Share it with Atlas and Cargo.
- [Frappe Connect](CONNECT.md): the planned contract for partner teams and partner links. Share it with the Connect developers.

## Billing

- [Billing architecture](../central/billing/ARCHITECTURE.md): the billing code map and domain rules.
- [Metered services API](../central/billing/docs/metered-services-api.md): usage reporting for metered services.
