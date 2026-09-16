# Central Spec

## v0.2 rewrite

- [Rewrite scope](REWRITE_SCOPE.md): proposed ownership, contracts, recovery, and data migration rules.
- [Delivery](DELIVERY.md): phase PRs into `v0.2` and their acceptance checks.
- [Validation](LOCAL_ENVIRONMENT.md): contract tests, populated migrations, and real-region evidence.

The v0.2 documents distinguish the proposed design from the verified baseline. Each implementation phase updates the current module specifications when its behavior lands.

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
