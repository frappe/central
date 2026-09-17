# Central Spec

## v0.2 staging milestone

- [Rewrite scope](REWRITE_SCOPE.md): Friday signup and server lifecycle, later work, ownership, and recovery.
- [Delivery](DELIVERY.md): phase PRs into `v0.2` and their acceptance checks.
- [Validation](LOCAL_ENVIRONMENT.md): contract tests, populated migrations, and real-region evidence.

Friday covers trial signup, Pilot server creation and access, plain Ubuntu creation, and server power actions. Rename, custom domains, and Cargo registration follow this milestone.

The v0.2 documents distinguish the proposed design from the verified baseline. Each implementation phase updates the current module specifications when its behavior lands.

## Current module specifications

- [Team network identity](../central/central/doctype/team/SPEC.md): allocation, immutability, and migration of tenant IDs.

- [Signing keys](../central/central/doctype/central_sso_settings/SPEC.md): separate Atlas and Pilot trust, operator initialization, and token verification.

- [Regional configuration](../central/central/doctype/atlas_instance/SPEC.md): signed connection checks, tenant selection, and regional identity.
- [Image offerings](../central/central/doctype/image_offering/SPEC.md): presentation records and on-demand regional System image discovery.
- [Proxy routes](../central/central/doctype/site_domain/SPEC.md): site and custom-domain routes on the regional proxy, with retry and delete.

## Existing specifications

- [IAM](IAM.md): Central identity and permission model. Its Atlas integration sections need review in phase 0.
- [Capabilities](../CAPABILITIES.md): the capability vocabulary and fixtures contract.
- [SSO](SSO.md): token flows and consumer contracts to check before the signing cutover.
- [Tunnel](TUNNEL.md): the tunnel path still present in the baseline Central code.
- [Atlas coordination](ATLAS_COORDINATION.md): earlier regional contracts that need replacement during the rewrite.
- [Refactor backlog](refactor_todo.md): prior findings to verify during the non-billing audit.

The earlier [execution plan](EXECUTION_PLAN.md) does not define the v0.2 delivery order. Do not use its Atlas OAuth or VM capability assumptions for the new integration. Use the verified contracts in [Rewrite scope](REWRITE_SCOPE.md).

## Billing

- [Billing documentation](../central/billing/docs/README.md): billing domain rules.

The rewrite preserves billing domain logic. Required resource references and integration changes carry their own tests and data patches.
